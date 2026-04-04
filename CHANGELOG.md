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