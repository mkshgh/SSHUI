# Changelog

## 2026-04-04

### Added
- **SSH File Explorer** — cross-platform seamless SFTP interactions
  - Click `Explore` button or use UI button to open file browser
  - Persistent tunneling through `asyncssh` (No more OS system `ssh`/`scp` freezes)
  - 10-second background TCP Port (Telnet-style) watchdog indicating connection health
  - Double-click navigation for rapid directory expansion 
  - Download/Upload directly natively with integrated Textual ProgressBars
  - Delete remote files with confirmation
  - View file preview contents

### Changed
- **Connectivity Tests**
  - Upgraded the main UI `Ping` button to dispatch genuine `icmplib` ICMP network probes (using OS fallback to bypass root restrictions) instead of TCP port 22 tests.
- **SSH File Explorer Interface Redesign**
  - **Dynamic Virtualization:** Completely dropped standard ListViews for Textual DataTables allowing traversal over deeply nested folders (10,000+ files) without UI lag.
  - **Column Data:** Files isolated into cleanly readable headers: Name, Type, Size, and Native 'Last Modified' timestamps via active SSH attributes.
  - **Local UI Search Filtering:** Injected `#file-search-bar` enabling immediate visual parsing/isolation of local lists.
  - **Remote Intelligent Path Suggester:** Added IntelliSense Auto-Completion directly mapping keyboard paths securely against remote SFTP endpoints.
  - **Native Click Intercepts:** Rolled out `ExplorerTable` enforcing absolute reliable keyboard/double-click operations natively.