# ufw-docker-sync

Author's itch fix for [docker/for-linux#690](https://github.com/docker/for-linux/issues/690)  
120+ comments. 500+ reactions. No fix in 2 years.

## Quick Start

```bash
curl -O https://raw.githubusercontent.com/olexandrshepitko-beep/ufw-docker-sync/main/ufw-docker-sync.py
python3 ufw-docker-sync.py --dry-run   # see what would change
sudo python3 ufw-docker-sync.py        # apply
```

No install. No dependencies. Works.

## Problem

Docker writes iptables rules directly, bypassing `ufw` (Uncomplicated Firewall).

```bash
ufw deny 8080              # expected: port 8080 blocked
docker run -p 8080:80 nginx   # actually: port 8080 OPEN → everyone sees nginx
```

ufw loses control. Docker's DOCKER chain takes priority over ufw's FORWARD policy.

Common "solutions" that break things:

- ❌ `--iptables=false` → breaks Docker networking entirely
- ❌ Disabling ufw → no firewall at all
- ❌ Manual iptables rules → not persistent across reboots

## Solution

One file. Zero dependencies. Enforces ufw policy against Docker iptables.

```bash
python3 ufw-docker-sync.py               # check + apply
python3 ufw-docker-sync.py --dry-run      # check only
python3 ufw-docker-sync.py --watch        # poll mode (systemd / cron)
```

### What it does

1. Reads ufw status (explicit allow/deny rules)
2. Detects Docker published host ports (`docker ps --format json`)
3. Parses iptables DOCKER-USER chain
4. Generates ufw after.rules fragment blocking conflicting ports
5. Applies via `ufw reload`

### Visual flow

```
ufw-docker-sync
  │
  ├── ufw_status()     → list of allowed/denied ports
  ├── docker_ports()   → published host ports
  ├── iptables_rules() → DOCKER-USER chain rules
  │
  └── diff → generate after.rules → ufw reload
```

## Install

**Option A — ad-hoc (literally curl):**

```bash
curl -O https://raw.githubusercontent.com/olexandrshepitko-beep/ufw-docker-sync/main/ufw-docker-sync.py
sudo python3 ufw-docker-sync.py
```

**Option B — systemd timer (recommended for servers):**

```bash
sudo ./ufw-docker-sync.py --install
# creates /etc/systemd/system/ufw-docker-sync.{service,timer}
# runs every 60s, checks ufw-docker consistency automatically
```

_Note: `--install` not yet implemented. PR welcome._

## Requirements

- Python 3.6+
- `iptables`, `docker`, `ufw` CLI on PATH
- Root for applying rules (`--dry-run` works without root)

## Why not just disable Docker iptables?

`--iptables=false` in `/etc/docker/daemon.json` sounds clean, but:

- Docker stops managing port mappings entirely — containers lose networking
- `docker run -p 80:80` → port not opened, container unreachable from outside
- Published ports, overlay networks, and ingress routing all break
- You're trading one config mess for another

ufw-docker-sync doesn't disable Docker's iptables. It adds a **DOCKER-USER chain rule** that enforces ufw policy on top — the way Docker intended (DOCKER-USER was designed for exactly this).

## Alternative approaches

| Approach | Works? | Maintenance | Trust |
|----------|--------|-------------|-------|
| [chaifeng/ufw-docker](https://github.com/chaifeng/ufw-docker) (original) | ✅ | Unmaintained since 2020 | Open source |
| Manual DOCKER-USER rules | ✅✅ | Breaks on reboot | None needed |
| **ufw-docker-sync (this)** | ✅✅ | Active, auto-sync | Open source, MIT |
| `--iptables=false` | ❌ Breaks networking | - | - |

## Feedback

If this helped you — open an issue, drop a star, or just say thanks.  
If it didn't — tell me what broke, I'll fix it.

- [Report a bug](https://github.com/olexandrshepitko-beep/ufw-docker-sync/issues/new)
- [Watch repo](https://github.com/olexandrshepitko-beep/ufw-docker-sync) for updates

## Related

- [docker/for-linux#690](https://github.com/docker/for-linux/issues/690) — original issue with 120+ comments
- [chaifeng/ufw-docker](https://github.com/chaifeng/ufw-docker) — original approach (unmaintained)

## License

MIT. One file, no deps, no magic. Fix your firewall in 10 seconds.
