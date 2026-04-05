# SSH Inventory Launcher

A keyboard-driven terminal SSH launcher for Ansible inventories, built with [Textual](https://github.com/Textualize/textual).

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
├── config.json            # auto-created — stores default forwards + theme
├── servers.csv
├── requirements.txt
├── .conf/                 # auto-created — cached inventory copies
├── inventory/
│   ├── cache.py           # .conf folder management, comment handling, refresh
│   └── loader.py          # YAML parsing, Host dataclass
├── ssh/
│   └── connection.py      # SSH command builder, terminal launcher
├── ui/
│   ├── app.py             # Textual UI, all modals
│   ├── config_modal.py    # Default port forwards config modal
│   ├── explorer_modal.py  # SSH file browser (experimental)
│   └── search.py          # Host and group filter logic
└── utils/
    ├── config.py          # config.json load/save
    └── logger.py          # Login event logger
```

## servers.csv

```csv
server_type,path
production,/path/to/ansible/production/inventory.yaml
staging,/path/to/ansible/staging/inventory.yaml
```

The top-level YAML key in each inventory file is auto-detected — it does not need to match `server_type`.

## Inventory Cache

On startup the app creates `.conf/` and copies each inventory file into it. Any commented-out lines are uncommented so all hosts are visible. Original files are never modified.

Press `R` to rebuild the cache from source.

## UI Layout

```
┌─ Server Groups ──────┬─ Hosts ────────────────────────────────────────────────┐
│                      │ [ Search hosts...          ] [Ping] [Telnet] [Explore] │
│  production          │ P   T   Name              IP                User  Port │
│  staging             │ OK  --  server1            10.0.0.1          ubuntu 22 │
│  k8s                 │ XX  OK  server2            10.0.0.2          ubuntu 22 │
└──────────────────────┴────────────────────────────────────────────────────────┘
```

- `P` — Ping result (TCP probe to port 22)
- `T` — Telnet result (TCP probe to configured port)
- `Defaults` — active default port forwards from config

Server groups are sorted A-Z (case-insensitive) and show the host count: `UATSERVER (10)`. Hosts within each group are also sorted A-Z (case-insensitive).

## Keybindings

| Key | Action |
|-----|--------|
| `↑ / ↓` | Navigate list |
| `Single Click` | Select / highlight host |
| `Double Click` | Open SSH session |
| `Enter` | Open SSH session (when host list is focused) |
| `F` | Open port forwarding options |
| `Right Click` | Open port forwarding options |
| `Ctrl+Y` | Yank (copy) host password to clipboard |
| `R` | Refresh inventory cache |
| `/ or S` | Focus host search bar |
| `Ctrl+G` | Open config (default port forwards) |
| `Ctrl+P` | Command palette (change theme, etc.) |
| `ESC` | Back |
| `Ctrl+Q` | Quit |

UI Buttons: `[Ping] [Telnet] [Explore]` — test connectivity or open file browser

## SSH Auth

Supports both password and key-based auth via inventory vars:

```yaml
hosts:
  server1:
    ansible_host: 10.0.0.1
    ansible_user: ubuntu
    ansible_port: 22
    ansible_ssh_private_key_file: ~/.ssh/id_rsa   # key auth
    # ansible_password: secret                    # or password auth
```

- Key auth: SSH launched with `-i keyfile`
- Password auth: password copied to clipboard on connect (or manually via `Ctrl+Y`)

## Port Forwarding

Press `F` or right-click a host to open the forwarding panel.

- Built-in presets: Postgres 5432, HTTP 80, HTTPS 443, 8080, 3000, Redis 6379
- Custom defaults from config (e.g. `7887:7887`) shown alongside presets
- One-off input field for additional forwards for this connection only
- Press `Enter` or click `Connect` to launch

SSH command produced:

```
ssh -L 5432:localhost:5432 -L 7887:localhost:7887 user@10.0.0.1 -p 22
```

## Config (Ctrl+G)

Opens the config modal to set default port forwards. These are:

- Pre-checked in the forwarding panel on every open
- Automatically applied on direct connect (Enter / double-click)

Custom format: `LOCAL:REMOTE`, comma separated:

```
7887:7887,9200:9200
```

Saved to `config.json` on Save.

## Theme

Change theme via `Ctrl+P → Change theme`. Saved to `config.json` automatically and restored on next launch.

Available themes include: `textual-dark`, `textual-light`, `nord`, `gruvbox`, `dracula`, `tokyo-night`, `catppuccin-mocha`, `catppuccin-latte`, `rose-pine`, `atom-one-dark`, and more.

## Connectivity Tests

Click `Ping` or `Telnet` beside the search bar to test all loaded hosts concurrently.

- `Ping` — ICMP network probe powered by OS fallback (no root required)
- `Telnet` — TCP connect to the host's configured port
- `OK` (green) = reachable, `XX` (red) = unreachable, `--` = untested
- 2 second timeout per host, all hosts tested in parallel

## File Explorer

Click `Explore` beside the search bar to open an SSH file browser for the selected host.

**Features:**
- Pure Python Persistent SFTP / SSH interactions powered by `asyncssh`
- Extremely fast navigation bypassing OS-level `ssh.exe` subprocesses and UI freezing
- 10-second background TCP Port (Telnet-style) watchdog (displays ONLINE/OFFLINE dynamically)
- Precise Transfer `ProgressBar` handling for recursive and standard operations
- **DataTable Architecture**: Complete DOM virtualization resolving lockups to safely render 10,000+ files
- **Data Columns**: Explicit structural splits showing [Name, Type, Size, Modified Date]
- **Auto-Complete Navigation**: Built-in native SSH IntelliSense (`SSHPathSuggester`) dynamically recommending remote directories as you type
- **Local Filtering**: Instantly isolate files recursively matching string inputs natively beneath the path bar
- Download files natively to local `Downloads/` folder
- Upload local files to the remote server
- Delete remote files securely or recursively dump directories
- View file contents (first 100 lines)

**Navigation:**
- Double-click directories to enter
- Double-click `(go back)` to go up
- Click `Home` to jump to home directory

**Notes:**
- Integrates seamlessly through python threads and yields absolute zero impact to the Textual interface event loop.
- No longer depends upon platform specific command line SSH or SCP bins.

## Logging

Every connection is appended to `ssh_login.log`:

```
2026-03-24 12:00:00 | production | server1 | ubuntu@10.0.0.1:22
```

## Build Executable

```bash
# without favicon
pip install pyinstaller
pyinstaller --onefile --name sshui main.py 
```

```bash
# with favicon
pip install pyinstaller
pyinstaller --onefile --name sshui --icon=favicon.ico main.py
```

Output: `dist/sshui.exe` (Windows) or `dist/sshui` (Linux/macOS).

### What to ship

```
dist/sshui        (or sshui.exe)
servers.csv
```

`config.json`, `.conf/`, and `ssh_login.log` are created automatically on first run.

### PyInstaller spec (optional)

A `sshui.spec` file is included for customised builds (icon, hidden imports, etc.):

```bash
pyinstaller sshui.spec
```

## Platform Notes

- Windows: tries `wt` (Windows Terminal) new tab first, falls back to a new PowerShell window
- Linux: tries tab-capable terminals (`gnome-terminal --tab`, `xfce4-terminal --tab`, `konsole --new-tab`, `tilix`) then falls back to `x-terminal-emulator` / `xterm` as a new window
- macOS: opens a new tab in the front Terminal window via AppleScript, falls back to a new window
- SSH must be in `PATH` on all platforms
