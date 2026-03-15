# SSH Inventory Launcher

A fast, keyboard-driven terminal SSH launcher for Ansible inventories.

## Project Structure

```
.
├── main.py               # Entry point
├── constants.py          # Shared constants (paths, default ports)
├── servers.csv           # Maps server group names to inventory YAML paths
├── ssh_login.log         # Auto-generated login log
├── requirements.txt
├── inventory/
│   ├── cache.py          # .conf folder management, comment handling, refresh
│   └── loader.py         # YAML parsing, Host dataclass
├── ssh/
│   └── connection.py     # SSH command builder, terminal launcher
├── ui/
│   ├── app.py            # Textual UI, port forwarding modal
│   └── search.py         # Host and group filter logic
└── utils/
    └── logger.py         # SSH login logger
```

The `.conf/` folder is auto-created at startup — do not edit it manually. It holds cleaned copies of your inventory files and is safe to delete.

## Setup

```bash
pip install -r requirements.txt
python main.py
```

## servers.csv format

```csv
server_type,path
production,/path/to/ansible/production/inventory.yaml
staging,/path/to/ansible/staging/inventory.yaml
```
here **server_type** is actually the root name of the **inventory.yaml** file.
So you might want to make it unique

eg:

```yaml
production:
    hosts:
        server:

staging:
    hosts:
        server:
```
## Keybindings

| Key       | Action                              |
|-----------|-------------------------------------|
| `↑ / ↓`   | Navigate groups or hosts            |
| `Enter`   | Select group / connect to host      |
| `/ or s`  | Search hosts (or groups)            |
| `Enter`   | Confirm search, focus list          |
| `R`       | Refresh inventory cache             |
| `ESC`     | Back / cancel                       |

## Building a standalone executable

Install PyInstaller:

```bash
pip install pyinstaller
```

Build:

```bash
pyinstaller --onefile --name sshui main.py
```

The executable will be at `dist/sshui` (or `dist/sshui.exe` on Windows).

### What to ship alongside the executable

PyInstaller bundles the Python code, but these files must sit next to the executable at runtime:

```
dist/
├── sshui.exe        # or sshui on Linux/macOS
├── servers.csv      # required — defines your inventory groups
```

The following are created automatically on first run and do not need to be shipped:

```
.conf/               # auto-created from servers.csv paths
ssh_login.log        # auto-created on first connection
```

### Notes

- The inventory YAML files referenced in `servers.csv` must be accessible from the machine running the executable.
- On Windows, SSH must be available in PATH (OpenSSH is included in Windows 10/11, or use Git Bash).
- On Linux, a desktop terminal emulator must be installed (`gnome-terminal`, `xterm`, etc.).
