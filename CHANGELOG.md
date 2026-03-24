# Changelog

### Added

#### Click & Keyboard Behavior
- Double-click on a host opens SSH directly (400 ms threshold)
- Single click selects/highlights only — no accidental SSH launches
- Right-click opens the port forwarding modal
- `Enter` opens SSH when the host list is focused (handled in `_on_key` with `prevent_default` to avoid ListView consuming it)
- `Ctrl+Y` yanks (copies) the focused host's password to clipboard — vim convention, avoids conflict with Textual's built-in `Ctrl+C` quit

#### ESC Behavior Fix
- `ESC` in the port forwarding modal now dismisses the modal only — does not clear the host list or navigate back
- Implemented by removing `escape` from `BINDINGS` and handling it in `_on_key` only when `screen_stack == 1` (no modal open)
- After dismissing a modal, host list remains populated

#### Connectivity Tests
- `Ping` and `Telnet` buttons added beside the host search bar
- Ping: TCP probe to port 22 (no root required)
- Telnet: TCP probe to the host's configured port
- Results shown inline per host: `OK` (green) / `XX` (red) / `--` (untested)
- All hosts tested concurrently via `asyncio.gather`, 2 second timeout
- Column header row added above host list (`P`, `T`, `Name`, `IP`, `User`, `Port`, `Defaults`)
- Header row hidden when no group is selected

#### Config System
- `utils/config.py` — loads/saves `config.json` (default forwards + theme)
- `ui/config_modal.py` — modal for setting default port forwards, opened with `Ctrl+G`
- `Ctrl+G` is globally intercepted via `_on_key` — works regardless of focused widget
- Default forwards pre-checked in the forwarding modal on every open
- Default forwards automatically applied on direct connect (Enter / double-click)
- Custom config forwards (e.g. `7887:7887`) shown as their own checkbox section in the forwarding modal
- Preset and custom checkboxes displayed side by side in a horizontal grid

#### Theme Persistence
- Theme saved automatically to `config.json` via `watch_theme` whenever changed (e.g. via `Ctrl+P`)
- Saved theme restored on startup via `on_mount`
- `AVAILABLE_THEMES` in `constants.py` updated to actual Textual 8.x registered names

#### SSH Key Auth
- `Host` dataclass gains `ssh_key` field
- `ansible_ssh_private_key_file` parsed from inventory YAML
- SSH command uses `-i keyfile` when key is present; otherwise password is copied to clipboard

#### Port Forwarding Modal — Connect Button
- `Connect` button added inside the forwarding modal alongside `Enter` to launch SSH
- Footer label updated: `ENTER / Click Connect → SSH    ESC → Cancel`

#### Defaults Column
- Host list shows a `Defaults` column with the local ports of all active default forwards (e.g. `5432 6379`)

### Changed
- `Ctrl+C` no longer overridden — Textual's built-in quit binding preserved
- `Ctrl+Q` added as explicit quit shortcut
- Footer updated: `Enter → SSH  Double-click → SSH  F / Right-click → Forwarding  Ctrl+Y → Yank pwd  Ctrl+G → Config  Ctrl+Q → Quit`
- Port forwarding modal widened to 80 columns for two-column checkbox layout
- Theme management removed from config modal — handled exclusively via command palette (`Ctrl+P`)

### Fixed
- `ESC` in forwarding modal was triggering app-level back action and clearing host list — fixed
- `Ctrl+C` was closing the app when used to copy — replaced yank with `Ctrl+Y`
- Host list not repopulating after modal dismiss — fixed by checking `screen_stack` before clearing
- YAML top-level key auto-detected as `yaml_header` — no longer required to match `server_type` in CSV
