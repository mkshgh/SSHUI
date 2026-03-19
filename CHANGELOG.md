# Changelog

## 2026-03-19

### Added

#### Ping / Telnet Connectivity Tests
- Two new buttons — `Ping` and `Telnet` — placed inline beside the host search bar in the right panel
- Buttons are hidden until a server group is selected, then appear alongside the search input
- Each button runs independently; clicking one does not affect the other's results
- Results persist in the list until the button is clicked again or a different group is selected
- While a test is running the button label changes to `...` and is disabled to prevent double-runs
- All hosts are tested concurrently using `asyncio.gather` so large inventories do not block the UI
- Each TCP probe has a 2 second timeout per host

**Ping button**
- Performs a TCP connect to port 22 on the host's IP
- Acts as a lightweight SSH reachability probe without requiring ICMP or root privileges
- Result shown in the `P` column of the host list

**Telnet button**
- Performs a TCP connect to the host's configured `ansible_port` (default 22)
- Verifies the actual service port is open and accepting connections
- Result shown in the `T` column of the host list

**Result indicators**
- `OK` rendered in green — TCP connection succeeded within timeout
- `XX` rendered in red — TCP connection failed or timed out
- `--` rendered in grey — not yet tested (default state)

#### Column Headers
- A permanent header row is now shown above the host list when a group is loaded
- Columns: `P` (ping status), `T` (telnet status), `Name`, `IP`, `User`, `Port`
- Header row uses a distinct background to visually separate it from the list items
- Header is hidden when no group is selected (same as the host list)

### Fixed

#### Search Bar Hiding Headers
- Previously the host search `Input` was toggled via `display` in CSS which caused it to overlap or displace the header row when shown
- Refactored the right panel layout: search input, Ping, and Telnet buttons now share a dedicated `search-row` container (`Horizontal`)
- The `search-row` container is toggled as a unit — the input inside it no longer has its own `display: none` rule
- Column headers live in a separate `host-header-row` container that is toggled independently
- This ensures the header is always visible below the search row and is never pushed out of view

### Changed
- `_status` dict replaced with two separate dicts `_ping_status` and `_telnet_status` to track results per test type independently
- `_render_hosts` updated to read both dicts and render two status columns per row
- Both status dicts are cleared when switching to a different server group
