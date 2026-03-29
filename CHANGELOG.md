# Changelog

## 2026-03-29

### Added
- Server groups in the left panel now display the host count next to the name — e.g. `UATSERVER (10)`
- Server groups sorted A-Z case-insensitively on load, refresh, and while filtering
- Hosts in the right panel sorted A-Z case-insensitively on every render (initial load, search filter, refresh, after connectivity tests)
- SSH now opens in a new tab where supported, falling back to a new window:
  - Windows: `wt --window 0 new-tab` (Windows Terminal), fallback to new PowerShell window
  - Linux: tries `gnome-terminal --tab`, `xfce4-terminal --tab`, `konsole --new-tab`, `tilix` in order, fallback to `x-terminal-emulator` / `xterm`
  - macOS: AppleScript opens new tab in front Terminal window, fallback to new window
