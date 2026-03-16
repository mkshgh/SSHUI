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
├── servers.csv
├── requirements.txt
├── inventory/
│   ├── cache.py       # .conf folder, comment stripping, refresh
│   └── loader.py      # YAML parsing, Host dataclass
├── ssh/
│   └── connection.py  # SSH command builder, terminal launcher
├── ui/
│   ├── app.py         # Textual UI, port forwarding modal
│   └── search.py      # Host and group filter logic
└── utils/
    └── logger.py      # Login logger
```

## servers.csv

Maps a label shown in the UI to an Ansible inventory YAML path.

```csv
server_type,path
production,/path/to/ansible/production/inventory.yaml
staging,/path/to/ansible/staging/inventory.yaml
```

The top-level YAML key in each file is auto-detected — it does not need to match `server_type`.

## Inventory Cache

On startup the app creates a `.conf/` folder and copies each inventory file into it with all commented lines uncommented. Original files are never modified. Press `R` to wipe and rebuild the cache from source.

## Keybindings

| Key | Action |
|-----|--------|
| `Up / Down` | Navigate list |
| `Enter` | Open SSH session |
| `F` | Open port forwarding options |
| `Right Click` | Open port forwarding options |
| `R` | Refresh inventory cache |
| `/ or S` | Search hosts or groups |
| `ESC` | Back |
| `Ctrl+Q` | Quit |

## Port Forwarding

Press `F` or right-click a host to open the forwarding panel before connecting.

Preset ports: Postgres (5432), HTTP (80), HTTPS (443), 8080, 3000, Redis (6379).

Custom format — enter as `LOCAL:REMOTE`, comma separated:

```
8081:80,5433:5432
```

SSH command produced:

```
ssh -L 5432:localhost:5432 -L 8081:localhost:80 user@10.0.0.1 -p 22
```

## Logging

Every connection is appended to `ssh_login.log`:

```
2026-03-16 14:22:01 | production | web-01 | ubuntu@10.0.0.1:22
```

## Build Executable

```bash
pip install pyinstaller
pyinstaller --onefile --name sshui main.py
```

Output: `dist/sshui.exe` (Windows) or `dist/sshui` (Linux/macOS).

Place `servers.csv` next to the executable. The `.conf/` folder and `ssh_login.log` are created automatically on first run.

## Platform Notes

- Windows: uses PowerShell (`start powershell`)
- Linux: tries `x-terminal-emulator`, `gnome-terminal`, `xterm` in order
- macOS: uses `osascript` to open Terminal.app
- SSH must be available in `PATH` on all platforms
