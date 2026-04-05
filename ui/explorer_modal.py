"""
SSH File Explorer Modal — Native asyncio SSH/SFTP file browser.
Uses asyncssh for persistent connections and SFTP for speed, completely bypassing subprocess freezing issues.
"""
from __future__ import annotations
import asyncio
import os
import re
import stat
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Optional, Tuple, Dict, Any

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import (
    Label, Button, ListView, ListItem, Input, Static, ProgressBar, DataTable
)
from datetime import datetime
from textual.containers import Horizontal, Vertical
from textual.worker import Worker, get_current_worker
from textual.message import Message

import asyncssh
from icmplib import async_ping
from inventory.loader import Host


def _sanitize_id(name: str) -> str:
    """Sanitize a name for use as a widget ID. Replace invalid chars with underscores."""
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    sanitized = re.sub(r'_+', '_', sanitized)
    sanitized = sanitized.rstrip('_')
    if sanitized and sanitized[0].isdigit():
        sanitized = 'f' + sanitized
    if not sanitized:
        sanitized = "unnamed"
    return sanitized


def _parse_sftp_name(name_obj: asyncssh.SFTPName) -> FileEntry:
    """Parse SFTPName attributes into cross-platform readable FileEntry."""
    name = name_obj.filename
    attrs = name_obj.attrs
    is_dir = False
    is_link = False
    link_target = ""
    size = attrs.size or 0
    mtime_str = ""
    
    if attrs.mtime is not None:
        try:
            mtime_str = datetime.fromtimestamp(attrs.mtime).strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass
    
    if attrs.permissions is not None:
        is_dir = stat.S_ISDIR(attrs.permissions)
        is_link = stat.S_ISLNK(attrs.permissions)
        if is_link and name_obj.longname and "->" in name_obj.longname:
            link_target = name_obj.longname.split("->")[-1].strip()
            
    return FileEntry(name, is_dir or is_link, size, "", link_target, mtime_str)


@dataclass
class FileEntry:
    name: str
    is_dir: bool
    size: int = 0
    perms: str = ""
    link_target: str = ""
    mtime: str = ""


class UploadState:
    def __init__(self):
        self.local_path: Optional[str] = None
        self.remote_path: Optional[str] = None
        self.local_name: Optional[str] = None


class DownloadState:
    def __init__(self):
        self.remote_path: Optional[str] = None
        self.local_path: Optional[str] = None
        self.name: Optional[str] = None


class DeleteState:
    def __init__(self):
        self.remote_path: Optional[str] = None
        self.name: Optional[str] = None
        self.is_dir: bool = False


class StatusMessage(Message):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class UploadCompleteMessage(Message):
    def __init__(self, success: bool, message: str, refresh: bool = False) -> None:
        super().__init__()
        self.success = success
        self.message = message
        self.refresh = refresh


class DownloadCompleteMessage(Message):
    def __init__(self, success: bool, message: str) -> None:
        super().__init__()
        self.success = success
        self.message = message


class DeleteCompleteMessage(Message):
    def __init__(self, success: bool, message: str, refresh: bool = False) -> None:
        super().__init__()
        self.success = success
        self.message = message
        self.refresh = refresh


class ProgressMessage(Message):
    def __init__(self, operation: str, stage: str, percentage: Optional[int] = None) -> None:
        super().__init__()
        self.operation = operation
        self.stage = stage
        self.percentage = percentage


class ConfirmModal(ModalScreen):
    """Simple confirmation dialog."""

    CSS = """
    ConfirmModal { align: center middle; }
    #confirm-box {
        width: 50;
        height: auto;
        background: $surface;
        border: tall $warning;
        padding: 1 2;
    }
    #confirm-buttons { margin-top: 1; height: 3; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self.message)
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", variant="error", id="btn-yes")
                yield Button("No", id="btn-no")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(False)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)


class ExplorerModal(ModalScreen):
    """
    File explorer using asyncssh natively.
    Establishes persistent connection over SFTP avoiding OS freezes.
    """

    CSS = """
    ExplorerModal { align: center middle; }
    #explorer-box {
        width: 90;
        height: 90%;
        background: $surface;
        border: tall $primary;
        padding: 0 1;
    }
    #explorer-header {
        height: 1;
        margin: 1 0;
        color: $accent;
    }
    #path-bar {
        height: 3;
        margin-bottom: 1;
    }
    #path-input { width: 1fr; }
    #file-search-bar { height: 3; margin-bottom: 1; }
    #file-list {
        height: 1fr;
        border: solid $primary;
    }
    #action-panel {
        height: 3;
        margin-top: 1;
    }
    #status-bar {
        height: 1;
        margin-top: 1;
        color: $text-muted;
    }
    #progress-bar {
        height: 1;
        margin-top: 1;
        display: none;
    }
    #progress-bar.visible {
        display: block;
    }
    """

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host
        self.current_path: str = "."
        self._home_path: str = "" 
        self.entries: List[FileEntry] = []
        self._id_to_name: Dict[str, str] = {}
        self._row_keys: List[str] = []
        self._upload_state = UploadState()
        self._download_state = DownloadState()
        self._delete_state = DeleteState()
        self._active_workers: Dict[str, Worker] = {}
        self._operation_in_progress: bool = False
        
        # AsyncSSH Persistent Client Connections
        self.conn: Optional[asyncssh.SSHClientConnection] = None
        self.sftp: Optional[asyncssh.SFTPClient] = None

    def compose(self) -> ComposeResult:
        with Vertical(id="explorer-box"):
            yield Label(
                f"[bold yellow]CONNECTING:[/bold yellow] {self.host.name} ({self.host.ip})",
                id="explorer-header"
            )
            with Horizontal(id="path-bar"):
                yield Button("Home", id="btn-home")
                yield Input(value=self.current_path, id="path-input")
                yield Button("Go", id="btn-go")
                yield Button("↻", id="btn-refresh")
            yield Input(placeholder="Search files...", id="file-search-bar")
            yield DataTable(id="file-list")
            with Horizontal(id="action-panel"):
                yield Button("Download", id="btn-download", variant="primary")
                yield Button("Upload", id="btn-upload")
                yield Button("Delete", id="btn-delete", variant="error")
                yield Button("Close", id="btn-close")
            yield Label("Ready", id="status-bar")
            yield ProgressBar(id="progress-bar", total=100)

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Name", "Type", "Size", "Modified")
        table.cursor_type = "row"
        self._start_worker("load_directory", self._load_directory("."))
        self.set_interval(10.0, self._check_connection)

    def on_unmount(self) -> None:
        """Clean up background workers and gracefully close SSH connections on escape."""
        self._cancel_all_workers()
        if self.sftp:
            self.sftp.exit()
        if self.conn:
            self.conn.close()

    def _update_header_status(self, status: str, color: str) -> None:
        """Helper to instantly update Header connectivity status from workers."""
        try:
            self.query_one("#explorer-header", Label).update(
                f"[bold {color}]{status}:[/bold {color}] {self.host.name} ({self.host.ip})"
            )
        except Exception:
            pass

    async def _ensure_connection(self) -> None:
        """Ensure we have an active SFTP and SSH tunnel native to the Event loop."""
        if self.conn and self.sftp:
            return  # Already hot and connected

        self.set_status("Establishing SSH Tunnel...")
        self._update_header_status("CONNECTING", "yellow")
        try:
            kwargs: Dict[str, Any] = {
                'host': self.host.ip,
                'port': self.host.port,
                'username': self.host.user,
                'known_hosts': None  # Disable strict Host Key enforcement internally
            }
            if self.host.password:
                kwargs['password'] = self.host.password
            if self.host.ssh_key:
                kwargs['client_keys'] = [self.host.ssh_key]
                
            self.conn = await asyncssh.connect(**kwargs)
            self.sftp = await self.conn.start_sftp_client()
            self._update_header_status("ONLINE", "green")
        except Exception as e:
            self.conn = None
            self.sftp = None
            self._update_header_status("OFFLINE", "red")
            raise Exception(f"Connection failed: {e}")

    def _check_connection(self) -> None:
        """Ping the host every 10s to verify connection status."""
        if not self._operation_in_progress:
            self._start_worker("ping", self._check_reachability(), group="ping", exclusive=True)

    async def _check_reachability(self) -> None:
        """Worker to execute background Telnet check returning OFFLINE if dead."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host.ip, self.host.port), timeout=2.0
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            self._update_header_status("ONLINE", "green")
        except Exception:
            self._update_header_status("OFFLINE", "red")
            if self.conn:
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                self.sftp = None

    def _normalize_path(self, path: str) -> str:
        if not path: return path
        if path != "/" and path.endswith("/"): path = path.rstrip("/")
        if path == "": path = "/"
        return path

    async def _load_directory(self, path: str) -> None:
        """Fetch directory contents over SFTP eagerly."""
        normalized_path = self._normalize_path(path)
        
        self.set_status(f"Loading {normalized_path}...")
        try:
            await self._ensure_connection()
            if self.sftp is None:
                raise Exception("SFTP not established")
            
            names = await self.sftp.readdir(normalized_path)
            
            entries = []
            for name_obj in names:
                if name_obj.filename in (".", ".."):
                    continue
                entries.append(_parse_sftp_name(name_obj))
            
            # Sort: Dirs first then alphabetical files
            entries.sort(key=lambda x: (not x.is_dir, x.name.lower()))
            
            self.current_path = normalized_path
            self.entries = entries
            self._id_to_name.clear()
            
            self.query_one("#path-input", Input).value = normalized_path
            await self._render_file_list(entries)
            self.set_status(f"{len(entries)} items")
            
        except Exception as e:
            error_msg = str(e)[:80]
            self.set_status(f"Error: {error_msg}")
            
            self.query_one("#path-input", Input).value = self.current_path
            table = self.query_one("#file-list", DataTable)
            table.clear()
            
            with self.app.batch_update():
                if self.current_path != "." and self.current_path != "/":
                    table.add_row("../ (go up)", "Dir", "", "", key="entry_parent")
                table.add_row(f"[red]Error: {error_msg}[/red]", "Error", "", "", key="error_entry")

    async def _render_file_list(self, entries: List[FileEntry]) -> None:
        """Render file list using DataTable for infinite virtualization scalability."""
        table = self.query_one("#file-list", DataTable)
        table.clear()
        self._row_keys = []
        
        with self.app.batch_update():
            if self.current_path != "." and self.current_path != "/":
                table.add_row("[dim]../ (go up)[/dim]", "Dir", "", "", key="entry_parent")
                self._row_keys.append("entry_parent")

            for entry in entries:
                safe_name = _sanitize_id(entry.name)
                self._id_to_name[safe_name] = entry.name
                
                if entry.is_dir:
                    display_name = f"📁 {entry.name}"
                    item_type = "Dir"
                    item_id = f"entry_dir_{safe_name}"
                    size_str = ""
                else:
                    if entry.link_target:
                        display_name = f"🔗 {entry.name}"
                        item_type = f"Link -> {entry.link_target}"
                        item_id = f"entry_link_{safe_name}"
                        size_str = ""
                    else:
                        display_name = f"📄 {entry.name}"
                        size_str = self._format_size(entry.size)
                        item_type = "File"
                        item_id = f"entry_file_{safe_name}"
                
                table.add_row(display_name, item_type, size_str, entry.mtime, key=item_id)
                self._row_keys.append(item_id)

    async def _go_home(self) -> None:
        if self._operation_in_progress:
            self.set_status("Please wait for current operation to complete")
            return
        
        if self._home_path:
            self._start_worker("load_directory", self._load_directory(self._home_path))
            return
        
        self.set_status("Detecting home directory...")
        self._start_worker("detect_home", self._detect_home_and_navigate())

    async def _detect_home_and_navigate(self) -> None:
        try:
            await self._ensure_connection()
            if self.conn:
                result = await self.conn.run('pwd', timeout=5.0)
                if result.exit_status == 0:
                    home = result.stdout.strip()
                    if home and home.startswith('/'):
                        self._home_path = home
                        await self._load_directory(home)
                        return
        except Exception:
            pass
        
        self._home_path = '/'
        await self._load_directory('/')

    def _format_size(self, size: int) -> str:
        """Format bytes to human readable."""
        if size < 1024: return f"{size}B"
        elif size < 1024 * 1024: return f"{size/1024:.1f}K"
        elif size < 1024 * 1024 * 1024: return f"{size/(1024*1024):.1f}M"
        return f"{size/(1024*1024*1024):.1f}G"

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Filter files based on the global search input."""
        if event.input.id == "file-search-bar":
            term = event.value.lower()
            filtered = [e for e in self.entries if term in e.name.lower()]
            await self._render_file_list(filtered)

    async def on_click(self, event) -> None:
        import time
        table = self.query_one("#file-list", DataTable)
        widget = event.widget
        while widget is not None:
            if widget is table:
                if event.button == 1:
                    now = time.monotonic()
                    last = getattr(self, "_last_click_time", 0)
                    self._last_click_time = now
                    if now - last < 0.4:
                        self._last_click_time = 0
                        try:
                            item_id = self._row_keys[table.cursor_row]
                        except Exception:
                            return
                        if self._operation_in_progress and (item_id == "entry_parent" or item_id.startswith("entry_dir_")):
                            self.set_status("Please wait for current operation to complete")
                            return
                        if item_id == "entry_parent":
                            parent = str(PurePosixPath(self.current_path).parent)
                            if parent == "." or self.current_path == ".":
                                parent = "."
                            self._start_worker("load_directory", self._load_directory(parent))
                        elif item_id.startswith("entry_dir_"):
                            safe_name = item_id.removeprefix("entry_dir_")
                            dir_name = self._id_to_name.get(safe_name, safe_name)
                            new_path = str(PurePosixPath(self.current_path) / dir_name)
                            self._start_worker("load_directory", self._load_directory(new_path))
                return
            widget = getattr(widget, "parent", None)

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter key dynamically to trigger traversal natively."""
        try:
            item_id = str(event.row_key.value)
        except Exception:
            return
            
        if self._operation_in_progress and (item_id == "entry_parent" or item_id.startswith("entry_dir_")):
            self.set_status("Please wait for current operation to complete")
            return
            
        if item_id == "entry_parent":
            parent = str(PurePosixPath(self.current_path).parent)
            if parent == "." or self.current_path == ".":
                parent = "."
            self._start_worker("load_directory", self._load_directory(parent))
        elif item_id.startswith("entry_dir_"):
            safe_name = item_id.removeprefix("entry_dir_")
            dir_name = self._id_to_name.get(safe_name, safe_name)
            new_path = str(PurePosixPath(self.current_path) / dir_name)
            self._start_worker("load_directory", self._load_directory(new_path))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if self._operation_in_progress and btn_id in ("btn-home", "btn-go", "btn-refresh"):
            self.set_status("Please wait for current operation to complete")
            return
        
        if btn_id == "btn-home":
            await self._go_home()
        elif btn_id == "btn-go":
            path = self.query_one("#path-input", Input).value
            self._start_worker("load_directory", self._load_directory(path))
        elif btn_id == "btn-refresh":
            self._start_worker("load_directory", self._load_directory(self.current_path))
        elif btn_id == "btn-download":
            await self._handle_download()
        elif btn_id == "btn-upload":
            await self._handle_upload()
        elif btn_id == "btn-delete":
            await self._handle_delete()
        elif btn_id == "btn-close":
            self.dismiss(None)

    def _get_selected_file(self) -> Optional[Tuple[str, bool]]:
        table = self.query_one("#file-list", DataTable)
        try:
            item_id = self._row_keys[table.cursor_row]
        except Exception:
            return None
        
        if item_id == "entry_parent": return ("..", True)
        elif item_id.startswith("entry_dir_"):
            safe_name = item_id.removeprefix("entry_dir_")
            return (self._id_to_name.get(safe_name, safe_name), True)
        elif item_id.startswith("entry_link_"):
            safe_name = item_id.removeprefix("entry_link_")
            return (self._id_to_name.get(safe_name, safe_name), True)
        elif item_id.startswith("entry_file_"):
            safe_name = item_id.removeprefix("entry_file_")
            return (self._id_to_name.get(safe_name, safe_name), False)
        return None

    def _start_worker(self, name: str, coro, group: str = None, exclusive: bool = False) -> Worker:
        worker = self.run_worker(coro, group=group, exclusive=exclusive)
        self._active_workers[name] = worker
        return worker

    def _cancel_worker(self, name: str) -> None:
        if name in self._active_workers:
            worker = self._active_workers[name]
            if not worker.is_cancelled:
                worker.cancel()
            del self._active_workers[name]

    def _cancel_all_workers(self) -> None:
        for name in list(self._active_workers.keys()):
            self._cancel_worker(name)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.is_finished:
            for name, worker in list(self._active_workers.items()):
                if worker == event.worker:
                    del self._active_workers[name]
                    break

    def on_close(self) -> None:
        self.on_unmount()

    def set_status(self, message: str) -> None:
        self.query_one("#status-bar", Label).update(message)

    def show_progress(self, value: int = 0) -> None:
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.update(progress=value)
        progress_bar.add_class("visible")

    def hide_progress(self) -> None:
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.remove_class("visible")
        
    def on_progress_message(self, event: ProgressMessage) -> None:
        if event.percentage is not None:
            self.show_progress(event.percentage)
            self.set_status(f"{event.operation}: {event.stage} ({event.percentage}%)")
        else:
            self.set_status(f"{event.operation}: {event.stage}")

    # ================= DOWNLOAD ================= 
    async def _handle_download(self) -> None:
        selected = self._get_selected_file()
        if not selected:
            self.set_status("No file selected")
            return
        
        self._operation_in_progress = True
        name, is_dir = selected
        remote_path = str(PurePosixPath(self.current_path) / name)
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads, exist_ok=True)
        local_path = os.path.join(downloads, name)

        self._download_state = DownloadState()
        self._download_state.remote_path = remote_path
        self._download_state.local_path = local_path
        self._download_state.name = name

        self._start_worker("download", self._download_flow(), group="download", exclusive=True)

    async def _download_flow(self) -> None:
        worker = get_current_worker()
        self.post_message(ProgressMessage("Download", "Checking SFTP Target", 10))
        
        try:
            await self._ensure_connection()
            if not self.sftp: raise Exception("No SFTP Tunnel Active")
            
            is_dir_download = False
            for entry in self.entries:
                if entry.name == self._download_state.name and entry.is_dir:
                    is_dir_download = True
                    break
                    
            def _progress(*args):
                # asyncssh passes (src, dst, bytes, total) or just (bytes, total)
                if len(args) >= 2:
                    bytes_transferred, total_bytes = args[-2], args[-1]
                else:
                    return
                if total_bytes > 0:
                    pct = int((bytes_transferred / total_bytes) * 100)
                    # Triggering internal cancel error if worker killed
                    if worker and worker.is_cancelled:
                        raise asyncssh.Error("Cancelled by user")
                    if pct > 100: pct = 100
                    self.post_message(ProgressMessage("Download", "Transferring", pct))

            self.post_message(ProgressMessage("Download", "Connecting...", 20))
            if is_dir_download:
                await self.sftp.get(self._download_state.remote_path, self._download_state.local_path, recurse=True, progress_handler=_progress)
            else:
                await self.sftp.get(self._download_state.remote_path, self._download_state.local_path, progress_handler=_progress)
                
            if worker.is_cancelled: return
            
            self.post_message(DownloadCompleteMessage(True, f"Downloaded -> Downloads/{self._download_state.name}"))
        except Exception as e:
            if worker.is_cancelled or "Cancelled" in str(e): return
            self.post_message(DownloadCompleteMessage(False, f"Download Error: {str(e)[:50]}"))

    def on_download_complete_message(self, event: DownloadCompleteMessage) -> None:
        self.set_status(event.message)
        self.hide_progress()
        self._operation_in_progress = False

    # ================= UPLOAD ================= 
    async def _handle_upload(self) -> None:
        self._operation_in_progress = True
        self.set_status("Preparing upload...")
        self.show_progress(0)
        self._start_worker("upload", self._upload_flow_with_modals(), group="upload", exclusive=True)

    async def _upload_flow_with_modals(self) -> None:
        worker = get_current_worker()
        
        self.post_message(ProgressMessage("Upload", "Requesting path"))
        local_path = await self.app.push_screen_wait(_InputModal("Local file system path:"))
        if not local_path or not os.path.exists(local_path):
            self.post_message(UploadCompleteMessage(False, "File path dropped or missing", refresh=False))
            return

        local_name = os.path.basename(local_path)
        remote_path = str(PurePosixPath(self.current_path) / local_name)
        
        try:
            await self._ensure_connection()
            if not self.sftp: raise Exception("No SFTP Tunnel Active")
            
            exists = False
            try:
                await self.sftp.stat(remote_path)
                exists = True
            except asyncssh.sftp.SFTPNoSuchFile:
                pass

            if exists:
                self.post_message(ProgressMessage("Upload", "Requesting overwrite confirm", 15))
                confirmed = await self.app.push_screen_wait(ConfirmModal(f"'{local_name}' exists. Overwrite via Tunnel?"))
                if not confirmed:
                    self.post_message(UploadCompleteMessage(False, "Cancelled", refresh=False))
                    return

            self.post_message(ProgressMessage("Upload", "Starting transfer", 20))
            is_dir_upload = os.path.isdir(local_path)
            
            def _progress(*args):
                if len(args) >= 2:
                    bytes_transferred, total_bytes = args[-2], args[-1]
                else:
                    return
                if total_bytes > 0:
                    pct = int((bytes_transferred / total_bytes) * 100)
                    if worker and worker.is_cancelled:
                        raise asyncssh.Error("Cancelled by user")
                    if pct > 100: pct = 100
                    self.post_message(ProgressMessage("Upload", "Transferring", pct))

            if is_dir_upload:
                await self.sftp.put(local_path, self.current_path, recurse=True, progress_handler=_progress)
            else:
                await self.sftp.put(local_path, remote_path, progress_handler=_progress)
                
            if worker.is_cancelled: return
            
            self.post_message(UploadCompleteMessage(True, f"Uploaded {local_name}", refresh=True))
        except Exception as e:
            if worker.is_cancelled or "Cancelled" in str(e): return
            self.post_message(UploadCompleteMessage(False, f"Upload Flow Error: {str(e)[:50]}", refresh=False))

    def on_upload_complete_message(self, event: UploadCompleteMessage) -> None:
        self.set_status(event.message)
        self.hide_progress()
        self._operation_in_progress = False
        if event.refresh:
            self._start_worker("load_directory", self._load_directory(self.current_path))

    # ================= DELETE ================= 
    async def _handle_delete(self) -> None:
        selected = self._get_selected_file()
        if not selected:
            self.set_status("No file selected")
            return
        
        self._operation_in_progress = True
        name, is_dir = selected
        if name == "..":
            self.set_status("Cannot delete parent directory")
            self._operation_in_progress = False
            return

        self._delete_state = DeleteState()
        self._delete_state.remote_path = str(PurePosixPath(self.current_path) / name)
        self._delete_state.name = name
        self._delete_state.is_dir = is_dir

        self._start_worker("delete", self._delete_flow(), group="delete", exclusive=True)

    async def _delete_flow(self) -> None:
        self.post_message(ProgressMessage("Delete", "Requesting confirmation", 10))
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Delete '{self._delete_state.name}' securely via SFTP? This cannot be undone.")
        )
        if not confirmed:
            self.post_message(DeleteCompleteMessage(False, "Delete cancelled", refresh=False))
            return

        try:
            await self._ensure_connection()
            if not self.sftp: raise Exception("No SFTP Tunnel Active")
            
            self.post_message(ProgressMessage("Delete", "Executing", 70))
            if self._delete_state.is_dir:
                await self.sftp.rmtree(self._delete_state.remote_path)
            else:
                await self.sftp.remove(self._delete_state.remote_path)
                
            self.post_message(DeleteCompleteMessage(True, f"Deleted {self._delete_state.name}", refresh=True))
        except Exception as e:
            self.post_message(DeleteCompleteMessage(False, f"Error: {str(e)[:50]}", refresh=True))

    def on_delete_complete_message(self, event: DeleteCompleteMessage) -> None:
        self.set_status(event.message)
        self.hide_progress()
        self._operation_in_progress = False
        if event.refresh:
            self._start_worker("load_directory", self._load_directory(self.current_path))


class _InputModal(ModalScreen):
    """Simple input modal for user prompts."""
    CSS = """
    _InputModal { align: center middle; }
    #input-box { width: 60; height: auto; background: $surface; border: tall $primary; padding: 1 2; }
    """
    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="input-box"):
            yield Label(self.prompt)
            yield Input(placeholder="Enter value...", id="input-field")
            with Horizontal():
                yield Button("OK", variant="primary", id="btn-ok")
                yield Button("Cancel", id="btn-cancel")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        elif event.key == "enter":
            val = self.query_one("#input-field", Input).value
            self.dismiss(val if val else None)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        val = self.query_one("#input-field", Input).value if event.button.id == "btn-ok" else None
        self.dismiss(val if val else None)


class _PreviewModal(ModalScreen):
    """Modal for viewing file contents."""
    CSS = """
    _PreviewModal { align: center middle; }
    #preview-box { width: 85; height: 85%; background: $surface; border: tall $primary; padding: 1 2; }
    #preview-title { height: 1; color: $accent; margin-bottom: 1; }
    #preview-content { height: 1fr; border: solid $primary; background: $surface-darken-1; padding: 1; overflow: auto; }
    #preview-footer { height: 3; margin-top: 1; }
    """
    def __init__(self, filename: str, content: str) -> None:
        super().__init__()
        self.filename = filename
        lines = content.split("\n")
        if len(lines) > 100:
            content = "\n".join(lines[:100]) + "\n\n... [truncated]"
        self.content = content

    def compose(self) -> ComposeResult:
        with Vertical(id="preview-box"):
            yield Label(f"View: {self.filename}", id="preview-title")
            yield Static(self.content, id="preview-content")
            with Horizontal(id="preview-footer"):
                yield Button("Close", id="btn-close")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)
