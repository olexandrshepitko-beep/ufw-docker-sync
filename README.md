# ufw-docker-sync

Author's itch fix for [docker/for-linux#690](https://github.com/docker/for-linux/issues/690)  
120+ comments. 500+ reactions. No fix in 2 years.

## Problem

Docker writes iptables rules directly, bypassing `ufw` (Uncomplicated Firewall).

```
ufw deny 8080    # expected: port 8080 blocked
docker run -p 8080:80 nginx   # actually: port 8080 OPEN
```

ufw loses control. Docker's DOCKER chain takes priority.

## Solution

Enforce ufw policy against Docker iptables.

```
python3 ufw-docker-sync.py               # check + apply
python3 ufw-docker-sync.py --dry-run      # check only
python3 ufw-docker-sync.py --watch        # poll mode (systemd / cron)
```

What it does:

1. Reads ufw status (explicit allow/deny rules)
2. Detects Docker published host ports (`docker ps --format json`)
3. Parses iptables DOCKER chain
4. Generates ufw after.rules fragment blocking conflicting ports
5. Applies via `ufw reload`

## Install

**Option A — ad-hoc:**

```bash
curl -O https://raw.githubusercontent.com/[YOUR_USER]/ufw-docker-sync/main/ufw-docker-sync.py
sudo python3 ufw-docker-sync.py
```

**Option B — systemd timer (recommended):**

```bash
sudo ./ufw-docker-sync.py --install
# creates /etc/systemd/system/ufw-docker-sync.{service,timer}
# runs every 60s, checks ufw-docker consistency
```

_Note: --install not yet implemented. PR welcome._

## Requirements

- Python 3.6+
- `iptables`, `docker`, `ufw` CLI available
- Root for applying rules (dry-run works without root)

## How it works

```
ufw-docker-sync
  │
  ├── ufw_status()     → list of allowed/denied ports
  ├── docker_ports()   → published host ports
  ├── iptables_rules() → DOCKER chain rules
  │
  └── compare → /etc/ufw/after.rules.d/ufw-docker-sync.rules
                → ufw reload
```

## Related

- [docker/for-linux#690](https://github.com/docker/for-linux/issues/690)
- [chaifeng/ufw-docker](https://github.com/chaifeng/ufw-docker) (original, unmaintained)

## License

MIT. One file, no deps, no magic.
