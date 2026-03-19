# SSH Inventory Launcher

A keyboard-driven terminal SSH launcher for Ansible inventories.

## Install

```bash
pip install -r requirements.txt
python main.py
```

## Project Structure

```
.
├── main.py
├── constants.py
├── config.json            # auto-created, stores default forwards + theme
├── servers.csv
├── requirements.txt
├── inventory/
│   ├── cache.py           # .conf folder, comment handling, refresh
│   └── loader.py          # YAML parsing, Host dataclass
├── ssh/
│   └── connection.py      # SSH command builder, terminal launcher
├── ui/
│   ├── app.py             # Textual UI, all modals
│   ├── config_modal.py    # Default port forwards config
│   └── search.py          # Host and group filter logic
└── utils/
    ├── config.py          # config.json load/save
    └── logger.py          # Login logger
```

## servers.csv

```csv
server_type,path
production,/path/to/ansible/production/inventory.yaml
staging,/path/to/ansible/staging/inventory.yaml
```

The top-level YAML key in each file is auto-detected — does not need to match `server_type`.

## Inventory Cache

On startup the app creates `.conf/` and copies each inventory file into it. Commented lines are uncommented so all hosts are visible. Original files are never modified. Press `R` to rebuild from source.

## UI Layout

```
[ Search hosts...          ] [Ping] [Telnet]
[ P   T   Name   IP   User   Port   Defaults ]
[ OK  --  server1  10.0.0.1  ubuntu  22  5432 6379 ]
```

- `P` — Ping result (TCP probe port 22)
- `T` — Telnet result (TCP probe configured port)
- `Defaults` — active default port forwards from config

## Keybindings

| Key | Action |
|-----|--------|
| `↑ / ↓` | Navigate list |
| `Enter` | Open SSH (with default forwards) |
| `Left Click` | Open SSH (with default forwards) |
| `F` | Open port forwarding options |
| `Right Click` | Open port forwarding options |
| `R` | Refresh inventory cache |
| `/ or S` | Search hosts or groups |
| `Ctrl+G` | Open config (default port forwards) |
| `Ctrl+P` | Command palette (change theme, etc.) |
| `ESC` | Back |
| `Ctrl+Q` | Quit |

## SSH Auth

Supports both password and key-based auth via inventory vars:

```yaml
hosts:
  server1:
    ansible_host: 10.0.0.1
    ansible_user: ubuntu
    ansible_port: 22
    ansible_ssh_private_key_file: ~/.ssh/id_rsa   # key auth
    ansible_password: secret                       # or password auth
```

Key auth uses `-i`. Password is copied to clipboard on connect.

## Port Forwarding

Press `F` or right-click a host to open the forwarding panel.

- Left column: built-in presets (Postgres, HTTP, HTTPS, 8080, 3000, Redis)
- Right column: your custom defaults from config (e.g. `7887:7887`)
- Bottom input: one-off additional forwards for this connection only

SSH command produced:

```
ssh -L 5432:localhost:5432 -L 7887:localhost:7887 user@10.0.0.1 -p 22
```

## Config (Ctrl+G)

Opens the config modal where you set default port forwards — these are pre-checked in the forwarding panel and automatically applied on direct connect (Enter/click).

Custom format in the input field — `LOCAL:REMOTE`, comma separated:

```
7887:7887,9200:9200
```

Config is saved to `config.json` automatically on Save.

## Theme

Change theme via `Ctrl+P → Change theme`. The selected theme is saved to `config.json` automatically and restored on next launch.

Available themes: `textual-dark`, `textual-light`, `nord`, `gruvbox`, `monokai`, `dracula`, `tokyo-night`, `flexoki`, `solarized-light`, `solarized-dark`, `catppuccin-mocha`, `catppuccin-latte`, `rose-pine`, `atom-one-dark`, and more.

## Connectivity Tests

Click `Ping` or `Telnet` beside the search bar to test all hosts concurrently.

- `Ping` — TCP connect to port 22 (no root required)
- `Telnet` — TCP connect to the host's configured port
- `OK` (green) = reachable, `XX` (red) = unreachable, `--` = untested
- 2 second timeout per host, runs in parallel

## Logging

Every connection appended to `ssh_login.log`:

```
2026-03-19 14:22:01 | production | web-01 | ubuntu@10.0.0.1:22
```

## Build Executable

```bash
pip install pyinstaller
pyinstaller --onefile --name sshui main.py
```

Output: `dist/sshui.exe` (Windows) or `dist/sshui` (Linux/macOS).

Ship `servers.csv` alongside the executable. `config.json`, `.conf/`, and `ssh_login.log` are created automatically on first run.

## Platform Notes

- Windows: opens PowerShell (`start powershell -NoExit -Command ...`)
- Linux: tries `x-terminal-emulator`, `gnome-terminal`, `xterm` in order
- macOS: uses `osascript` to open Terminal.app
- SSH must be in `PATH` on all platforms
