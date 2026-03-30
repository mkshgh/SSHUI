# Changelog

## 2026-03-29

### Fixed
- Clicking a host after sorting was connecting to the wrong server — index lookup was against unsorted list while display was sorted; sorting moved to `_visible_hosts()` so both are always in sync

## 2026-03-30

### Changed
- Host sorting moved from runtime to cache-write time — hosts are now sorted A-Z (case-insensitive) inside each group when the YAML is copied into `.conf/` on startup or `R` refresh
- Removed all runtime sorting from `_visible_hosts()` and `_render_hosts()` — no more risk of index/display mismatch during search or navigation
- `.conf/` files are now the single source of truth for host order
