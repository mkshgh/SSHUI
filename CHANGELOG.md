# Changelog

## 2026-03-19 (session 2)

### Added

#### Config System
- New `utils/config.py` module — loads and saves `config.json` with defaults for `default_forwards` and `theme`
- New `ui/config_modal.py` — config modal opened with `Ctrl+G`, always accessible regardless of focused widget
- Default port forwards set in config are pre-checked in the port forwarding modal on every open
- Default port forwards are also applied automatically on direct connect (Enter / left-click)
- Custom config forwards (e.g. `7887:7887`) appear as their own checkbox section in the forwarding modal alongside built-in presets
- Preset and custom default checkboxes displayed side by side in a horizontal grid to save vertical space

#### Theme Persistence
- Theme is now saved automatically to `config.json` whenever changed (e.g. via `Ctrl+P → Change theme`)
- Saved theme is restored on next launch via `on_mount`
- `AVAILABLE_THEMES` in `constants.py` updated to reflect actual registered theme names in Textual 8.x (`textual-dark`, `nord`, `dracula`, `tokyo-night`, etc.)

#### Defaults Column in Host List
- Host list now shows a `Defaults` column displaying the local ports of all active default forwards (e.g. `5432 6379`)
- Column is empty when no defaults are configured

#### Global Config Shortcut
- `Ctrl+G` opens the config modal from anywhere — idle screen, group list, host list, or while search input is focused
- Implemented via `_on_key` at the app root level to intercept before any widget consumes the key

### Changed
- Port forwarding modal widened to 80 columns to accommodate two-column checkbox layout
- Config modal theme section removed — theme is now managed exclusively via the command palette (`Ctrl+P`)
- `ForwardingModal` now accepts `default_forwards` from config and splits them into preset vs custom groups
- Footer binding for config changed from `C` to `Ctrl+G` to avoid conflict with text input widgets

### Fixed
- `InvalidThemeError` on startup — default theme was `"dark"` which is not a registered Textual theme; corrected to `"textual-dark"`
- Theme setter now guarded — only applied if the theme name exists in `_registered_themes`, preventing crashes on invalid config values
- `DuplicateIds` crash in theme suggestion list — removed IDs from suggestion `ListItem` widgets and read label text directly on selection instead
- Config `C` shortcut not firing when search input had focus — replaced with `Ctrl+G` and `_on_key` interception

---
