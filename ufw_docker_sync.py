#!/usr/bin/env python3
"""
ufw-docker-sync — enforce ufw rules against Docker iptables.

Problem: Docker writes iptables rules directly, bypassing ufw.
This script detects and restores ufw policy after Docker changes iptables.

Usage:
  python3 ufw-docker-sync.py          # check + fix
  python3 ufw-docker-sync.py --dry-run # check only
  python3 ufw-docker-sync.py --watch   # continuous mode (systemd/poll)

Bare. No dependencies beyond Python 3.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

# ─── helpers ──────────────────────────────────────────────

def run(cmd, timeout=10, check=True):
    """Run shell command, return stdout."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            print(f"[warn] '{' '.join(cmd)}' exited {r.returncode}: {r.stderr.strip()[:200]}")
        return r.stdout, r.returncode
    except FileNotFoundError:
        return "", -1
    except subprocess.TimeoutExpired:
        return "", -2


def iptables_rules():
    """Return current iptables filter rules."""
    out, _ = run(["iptables-save", "-t", "filter"], check=False)
    return out


def docker_ports():
    """Detect host ports Docker is publishing."""
    out, _ = run(["docker", "ps", "--format", "{{json .}}"], check=False)
    ports = []
    for line in out.strip().split("\n"):
        if not line.strip():
            continue
        try:
            info = json.loads(line)
            port_str = info.get("Ports", "")
            if not port_str:
                continue
            for part in port_str.split(","):
                m = re.search(r"0\.0\.0\.0:(\d+)->", part)
                if m:
                    ports.append(int(m.group(1)))
        except json.JSONDecodeError:
            continue
    return list(set(ports))


def ufw_status():
    """Return parsed ufw status."""
    out, rc = run(["ufw", "status", "verbose"], check=False)
    if rc != 0:
        return {"enabled": False, "rules": []}
    enabled = "Status: active" in out
    rules = []
    for line in out.split("\n"):
        m = re.match(r"^(\d+)/tcp\s+.*(ALLOW|DENY)", line)
        if m:
            rules.append({"port": int(m.group(1)), "action": m.group(2).lower()})
    return {"enabled": enabled, "rules": rules}


def container_networks():
    """Detect Docker bridge networks and subnets."""
    out, _ = run(["docker", "network", "ls", "--filter", "driver=bridge", "--format", "{{.ID}}"], check=False)
    networks = []
    for nid in out.strip().split("\n"):
        if not nid.strip():
            continue
        inspect_out, _ = run(["docker", "network", "inspect", nid.strip(), "--format", "{{json .IPAM.Config}}"], check=False)
        try:
            configs = json.loads(inspect_out)
            for cfg in configs:
                subnet = cfg.get("Subnet")
                if subnet:
                    networks.append(subnet)
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
    return networks


# ─── core check ───────────────────────────────────────────

def check(dry_run=False):
    """
    Detect docker-ufw mismatch and produce fix.
    Returns dict with findings.
    """
    print(f"ufw-docker-sync [{datetime.now().isoformat()}]")
    print(f"{'─' * 50}")

    # 1. ufw state
    ufw = ufw_status()
    print(f"ufw enabled: {ufw['enabled']}")
    print(f"ufw explicit rules: {len(ufw['rules'])}")

    if not ufw["enabled"]:
        print("ufw disabled — nothing to enforce")
        return {"status": "skip"}

    # 2. Docker published ports
    dports = docker_ports()
    print(f"Docker published host ports: {dports}")

    # 3. iptables DOCKER chain
    rules = iptables_rules()
    docker_chain = []
    in_docker = False
    for line in rules.split("\n"):
        if line.startswith("*filter"):
            in_docker = False
        if "*filter" in line:
            in_docker = False
        if line.startswith(":DOCKER "):
            in_docker = True
            continue
        if line.startswith("COMMIT"):
            in_docker = False
        if in_docker and line.startswith("-A DOCKER"):
            docker_chain.append(line)

    print(f"iptables DOCKER chain rules: {len(docker_chain)}")

    # 4. Container networks
    subnets = container_networks()
    print(f"Docker bridge subnets: {subnets}")

    # 5. Detect mismatch
    issues = []
    for port in dports:
        # is port blocked by ufw?
        blocked = any(r["port"] == port and r["action"] == "deny" for r in ufw["rules"])
        allowed = any(r["port"] == port and r["action"] == "allow" for r in ufw["rules"])

        if blocked:
            issues.append({
                "port": port,
                "problem": "denied_by_ufw_but_exposed_by_docker",
            })

        elif not allowed:
            issues.append({
                "port": port,
                "problem": "not_explicitly_allowed_by_ufw_but_exposed_by_docker",
            })

    # 6. Produce fix if needed
    if issues:
        print(f"\n{'!' * 50}")
        print(f"Issues found: {len(issues)}")

        for iss in issues:
            print(f"  Port {iss['port']}: {iss['problem']}")

        if not dry_run:
            # Generate ufw after.rules fragment
            after_rules = []
            after_rules.append(f"# ufw-docker-sync {datetime.now().isoformat()}")
            after_rules.append("*filter")
            after_rules.append(":ufw-docker-sync - [0:0]")

            for iss in issues:
                port = iss["port"]
                after_rules.extend([
                    f"-A ufw-docker-sync -p tcp --dport {port} -j DROP",
                    f"-A ufw-docker-sync -p udp --dport {port} -j DROP",
                ])

            after_rules.append("COMMIT")
            after_rules_text = "\n".join(after_rules)
            print(f"\nFix plan:")
            print(f"  Create /etc/ufw/after.rules fragment to block:")
            for iss in issues:
                print(f"    port {iss['port']}")

            apply_path = "/etc/ufw/after.rules.d/ufw-docker-sync.rules"
            print(f"\n  Apply: sudo tee {apply_path} <<< '{after_rules_text}'")
            print(f"  Then: sudo ufw reload")

            if os.geteuid() == 0 or os.getenv("SUDO_USER"):
                # Can apply directly
                os.makedirs("/etc/ufw/after.rules.d", exist_ok=True)
                with open("/etc/ufw/after.rules.d/ufw-docker-sync.rules", "w") as f:
                    f.write(after_rules_text)
                print("  ✅ Applied locally (root)")
                run(["ufw", "reload"], check=False)
                print("  ✅ ufw reloaded")
            else:
                print("  ⚠️ Cannot apply — not root.")
                print("  Run with sudo or copy the rules manually.")

        else:
            print(f"\n(dry-run — no changes)")

    else:
        print(f"\n{'=' * 50}")
        print("No issues detected. ufw and Docker are consistent.")
        print(f"{'=' * 50}")

    return {
        "checked": datetime.now().isoformat(),
        "ufw_enabled": ufw["enabled"],
        "docker_ports": dports,
        "issues": issues,
        "dry_run": dry_run,
    }


def watch(interval=60, dry_run=True):
    """Poll mode."""
    print(f"ufw-docker-sync watch mode (interval={interval}s)")
    while True:
        check(dry_run=dry_run)
        time.sleep(interval)


# ─── CLI ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Enforce ufw rules against Docker iptables."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Check only, no changes.")
    parser.add_argument("--watch", action="store_true",
                        help="Continuous poll mode.")
    parser.add_argument("--interval", type=int, default=60,
                        help="Poll interval in seconds (default: 60).")
    args = parser.parse_args()

    if args.watch:
        watch(interval=args.interval, dry_run=args.dry_run)
    else:
        result = check(dry_run=args.dry_run)
        sys.exit(1 if result.get("issues") else 0)


if __name__ == "__main__":
    main()
