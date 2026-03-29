# Changelog

## 2026-03-29

### Fixed
- Clicking a host after sorting was connecting to the wrong server — index lookup was against unsorted list while display was sorted; sorting moved to `_visible_hosts()` so both are always in sync
