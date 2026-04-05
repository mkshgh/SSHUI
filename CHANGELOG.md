# Changelog

## 2026-04-05

### Changed
- **SSH File Explorer Interface Redesign**
  - **Dynamic Virtualization:** Completely dropped standard ListViews for Textual DataTables allowing traversal over deeply nested folders (10,000+ files) without UI lag.
  - **Column Data:** Files isolated into cleanly readable headers: Name, Type, Size, and Native 'Last Modified' timestamps via active SSH attributes.
  - **Local UI Search Filtering:** Injected `#file-search-bar` enabling immediate visual parsing/isolation of local lists.
  - **Remote Intelligent Path Suggester:** Added IntelliSense Auto-Completion directly mapping keyboard paths securely against remote SFTP endpoints.
  - **Native Click Intercepts:** Rolled out `ExplorerTable` enforcing absolute reliable keyboard/double-click operations natively.