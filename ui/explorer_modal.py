"""
SSH File Explorer Modal — Non-invasive file browser using system SSH/SCP.
Uses existing SSH session logic, lazy loading, and minimal dependencies.
"""
from __future__ import annotations
import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Optional, Tuple, Dict

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import (
    Label, Button, ListView, ListItem, Input, Static, ProgressBar
)
from textual.containers import Horizontal, Vertical
from textual.worker import Worker, get_current_worker
from textual.message import Message

from inventory.loader import Host


def _sanitize_id(name: str) -> str:
    """Sanitize a name for use as a widget ID. Replace invalid chars with underscores."""
    # Replace any character that isn't alphanumeric, underscore, or hyphen with underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    # Collapse multiple consecutive underscores to single
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip only trailing underscores (keep leading to distinguish hidden files)
    sanitized = sanitized.rstrip('_')
    # Ensure it doesn't start with a number by prefixing with 'f' if needed
    if sanitized and sanitized[0].isdigit():
        sanitized = 'f' + sanitized
    # Fallback if name was all special chars
    if not sanitized:
        sanitized = "unnamed"
    return sanitized


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text."""
    # ANSI escape sequence pattern
    ansi_pattern = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_pattern.sub('', text)


@dataclass
class FileEntry:
    name: str
    is_dir: bool
    size: int = 0
    perms: str = ""
    link_target: str = ""


class UploadState:
    """Holds state for upload process across async boundaries."""
    def __init__(self):
        self.local_path: Optional[str] = None
        self.remote_path: Optional[str] = None
        self.local_name: Optional[str] = None
        self.needs_confirmation: bool = False
        self.confirmed: bool = False


class DownloadState:
    """Holds state for download process across async boundaries."""
    def __init__(self):
        self.remote_path: Optional[str] = None
        self.local_path: Optional[str] = None
        self.name: Optional[str] = None
        self.needs_confirmation: bool = False
        self.confirmed: bool = False


class DeleteState:
    """Holds state for delete process across async boundaries."""
    def __init__(self):
        self.remote_path: Optional[str] = None
        self.name: Optional[str] = None
        self.is_dir: bool = False
        self.confirmed: bool = False


class StatusMessage(Message):
    """Message to update status bar from worker."""
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message


class UploadCompleteMessage(Message):
    """Message sent when upload completes (success or failure)."""
    def __init__(self, success: bool, message: str, refresh: bool = False) -> None:
        super().__init__()
        self.success = success
        self.message = message
        self.refresh = refresh


class DownloadCompleteMessage(Message):
    """Message sent when download completes (success or failure)."""
    def __init__(self, success: bool, message: str) -> None:
        super().__init__()
        self.success = success
        self.message = message


class DeleteCompleteMessage(Message):
    """Message sent when delete completes (success or failure)."""
    def __init__(self, success: bool, message: str, refresh: bool = False) -> None:
        super().__init__()
        self.success = success
        self.message = message
        self.refresh = refresh


class ProgressMessage(Message):
    """Message to report progress from worker."""
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
    File explorer using system SSH commands.
    No persistent connections — executes commands on demand.
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
        self._home_path: str = ""  # Will be detected on first use
        self.entries: List[FileEntry] = []
        self._id_to_name: Dict[str, str] = {}  # Maps sanitized IDs to original names
        self._upload_state = UploadState()  # Track upload state across async boundaries
        self._download_state = DownloadState()  # Track download state across async boundaries
        self._delete_state = DeleteState()  # Track delete state across async boundaries
        self._active_workers: Dict[str, Worker] = {}  # Track active workers for cancellation
        self._operation_in_progress: bool = False  # Track if upload/download/delete is running
        self._upload_proc: Optional[asyncio.subprocess.Process] = None  # Store subprocess for cancellation

    def compose(self) -> ComposeResult:
        with Vertical(id="explorer-box"):
            yield Label(
                f"[bold red]EXPERIMENTAL:[/bold red] {self.host.name} ({self.host.ip})",
                id="explorer-header"
            )
            with Horizontal(id="path-bar"):
                yield Button("Home", id="btn-home")
                yield Input(value=self.current_path, id="path-input")
                yield Button("Go", id="btn-go")
                yield Button("↻", id="btn-refresh")
            yield ListView(id="file-list")
            with Horizontal(id="action-panel"):
                yield Button("Download", id="btn-download", variant="primary")
                yield Button("Upload", id="btn-upload")
                yield Button("Delete", id="btn-delete", variant="error")
                yield Button("Close", id="btn-close")
            yield Label("Ready", id="status-bar")
            yield ProgressBar(id="progress-bar", total=100)

    async def on_mount(self) -> None:
        self._start_worker("load_directory", self._load_directory("."))

    def _normalize_path(self, path: str) -> str:
        """Normalize path to handle trailing slashes consistently."""
        if not path:
            return path
        
        # Remove trailing slashes except for root
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        
        # Ensure root is just "/"
        if path == "":
            path = "/"
        
        return path

    async def _load_directory(self, path: str) -> None:
        """Lazy load: fetch directory contents via SSH."""
        normalized_path = self._normalize_path(path)
        
        self.set_status(f"Loading {normalized_path}...")
        entries, error = await self._ssh_ls(normalized_path)
        if error:
            # Show error but don't change current directory
            error_msg = error[:80] if len(error) > 80 else error
            self.set_status(f"Error: {error_msg}")
            # Reset path input back to current working path
            self.query_one("#path-input", Input).value = self.current_path
            # Clear the file list but add navigation options so user isn't stuck
            file_list = self.query_one("#file-list", ListView)
            await file_list.clear()
            # Add parent entry if not at root so user can navigate away
            if self.current_path != "." and self.current_path != "/":
                await file_list.append(
                    ListItem(Label("[dim]../ (go up)[/dim]", markup=True), id="entry_parent")
                )
            # Show error message in file list
            await file_list.append(
                ListItem(Label(f"[red]Error: {error_msg}[/red]", markup=True), id="error_entry")
            )
            return

        self.current_path = normalized_path
        self.entries = entries
        self._id_to_name.clear()
        self.query_one("#path-input", Input).value = normalized_path
        await self._render_file_list(entries)
        self.set_status(f"{len(entries)} items")

    async def _render_file_list(self, entries: List[FileEntry]) -> None:
        """Render file list with lazy loading for large directories."""
        file_list = self.query_one("#file-list", ListView)
        await file_list.clear()

        # Add parent entry if not at root
        if self.current_path != "." and self.current_path != "/":
            await file_list.append(
                ListItem(Label("[dim]../ (go up)[/dim]", markup=True), id="entry_parent")
            )

        # Add entries in batches to prevent UI lag
        batch_size = 20  # Reduced batch size for better responsiveness
        for i, entry in enumerate(entries):
            safe_name = _sanitize_id(entry.name)
            self._id_to_name[safe_name] = entry.name
            
            if entry.is_dir:
                display = f"📁 {entry.name}/"
                item_id = f"entry_dir_{safe_name}"
            else:
                if entry.link_target:
                    display = f"🔗 {entry.name} -> {entry.link_target}"
                    item_id = f"entry_link_{safe_name}"
                else:
                    size_str = self._format_size(entry.size)
                    display = f"📄 {entry.name} ({size_str})"
                    item_id = f"entry_file_{safe_name}"
            
            await file_list.append(
                ListItem(Label(display, markup=True), id=item_id)
            )
            
            # Yield control more frequently to prevent blocking
            if i % batch_size == 0 and i > 0:
                await asyncio.sleep(0)  # Immediate yield for better responsiveness

    async def _go_home(self) -> None:
        """Navigate to the user's home directory, fallback to root."""
        # Block navigation during file operations
        if self._operation_in_progress:
            self.set_status("Please wait for current operation to complete")
            return
        
        # If we already know the home path, use it
        if self._home_path:
            self._start_worker("load_directory", self._load_directory(self._home_path))
            return
        
        # Try to detect home directory
        self.set_status("Detecting home directory...")
        self._start_worker("detect_home", self._detect_home_and_navigate())

    async def _detect_home_and_navigate(self) -> None:
        """Worker to detect home directory and navigate."""
        cmd = self._build_ssh_command('echo $HOME')
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                home = _strip_ansi(stdout.decode().strip())
                if home and home.startswith('/'):
                    self._home_path = home
                    await self._load_directory(home)
                    return
        except Exception:
            pass
        
        # Fallback to root directory
        self._home_path = '/'
        await self._load_directory('/')

    def _format_size(self, size: int) -> str:
        """Format bytes to human readable."""
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size/1024:.1f}K"
        elif size < 1024 * 1024 * 1024:
            return f"{size/(1024*1024):.1f}M"
        return f"{size/(1024*1024*1024):.1f}G"

    async def _ssh_ls(self, path: str, timeout: int = 15) -> Tuple[Optional[List[FileEntry]], Optional[str]]:
        """Execute ls via SSH and parse output. Returns (entries, error_message)."""
        # Use --color=never to disable ANSI color codes and -A for better parsing
        cmd = self._build_ssh_command(f'ls -la --color=never -A "{path}"')
        try:
            # Use CREATE_NO_WINDOW on Windows to prevent console inheritance
            import sys
            kwargs = {}
            if sys.platform == 'win32':
                kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs
            )
            # Add timeout to prevent hanging
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            
            if proc.returncode != 0:
                err_msg = _strip_ansi(stderr.decode()).strip() if stderr else ""
                return None, err_msg or f"Failed to list {path}"
            # Strip ANSI sequences and parse
            clean_output = _strip_ansi(stdout.decode()) if stdout else ""
            # Limit output size to prevent UI freezing
            if len(clean_output) > 50000:  # 50KB limit
                clean_output = clean_output[:50000] + "\n... [truncated]"
            return self._parse_ls_output(clean_output.strip()), None
        except asyncio.TimeoutError:
            return None, f"Timeout listing directory {path}"
        except Exception as e:
            return None, str(e)

    def _parse_ls_output(self, output: str) -> List[FileEntry]:
        """Parse ls -la output into FileEntry objects."""
        entries = []
        for line_num, line in enumerate(output.split("\n")):
            line = line.strip()
            if not line:
                continue
            # Skip "total X" line
            if line.startswith("total "):
                continue
                
            # Skip lines that don't look like ls output or have permission issues
            # Valid ls lines start with: - (file), d (dir), l (link), etc.
            if (len(line) < 2 or line[0] not in "-dlcbsp"):
                continue
                
            try:
                parts = line.split()
                if len(parts) < 6:
                    continue
                    
                # Extract permissions from first field
                perms = parts[0]
                is_dir = perms.startswith("d")
                
                # Find the name field - it's usually the last field(s)
                # Handle names with spaces by finding the start of the name field
                # ls format: perms links owner group size month day time name
                # Name starts after the time field (usually position 8+)
                if len(parts) >= 9:
                    name_parts = parts[8:]
                    name = " ".join(name_parts)
                else:
                    name = parts[-1]
                
                # Handle symlinks (name -> target)
                is_link = " -> " in name
                link_target = ""
                if is_link:
                    name_parts = name.split(" -> ")
                    name = name_parts[0]
                    link_target = name_parts[1] if len(name_parts) > 1 else ""
                    
                if name in (".", ".."):
                    continue
                    
                # Try to find size field - it's usually at position 4 for files
                # Directories often show 4096 or similar, but some systems show different values
                size = 0
                if len(parts) >= 5:
                    try:
                        size = int(parts[4])
                    except ValueError:
                        # If size parsing fails, use 0 for directories
                        if is_dir:
                            size = 0
                        else:
                            continue  # Skip files with invalid sizes
                        
                entries.append(FileEntry(name, is_dir or is_link, size, perms, link_target))
                
            except Exception:
                # Skip malformed lines but continue processing others
                continue
                
        return entries

    def _build_ssh_command(self, remote_cmd: str) -> str:
        """Build SSH command using host credentials."""
        parts = ["ssh", "-q"]  # -q suppresses warnings and banners
        if self.host.ssh_key:
            parts.append(f'-i "{self.host.ssh_key}"')
        parts.extend([
            f'-p {self.host.port}',
            f'{self.host.user}@{self.host.ip}',
            remote_cmd
        ])
        return " ".join(parts)

    def _build_scp_command(self, remote_path: str, local_path: str, download: bool = True) -> str:
        """Build SCP command for file transfer."""
        parts = ["scp"]
        if self.host.ssh_key:
            parts.append(f'-i "{self.host.ssh_key}"')
        parts.append(f'-P {self.host.port}')
        if download:
            parts.append(f'{self.host.user}@{self.host.ip}:"{remote_path}"')
            parts.append(f'"{local_path}"')
        else:
            parts.append(f'"{local_path}"')
            parts.append(f'{self.host.user}@{self.host.ip}:"{remote_path}"')
        return " ".join(parts)

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle file/directory selection."""
        # Selection only - navigation handled by on_click
        pass

    async def on_click(self, event) -> None:
        """Handle clicks for double-click navigation."""
        import time
        
        file_list = self.query_one("#file-list", ListView)
        widget = event.widget
        while widget is not None:
            if widget is file_list:
                if event.button == 1:
                    now = time.monotonic()
                    last = getattr(self, "_last_click_time", 0)
                    self._last_click_time = now
                    if now - last < 0.4:  # double-click threshold
                        self._last_click_time = 0
                        item = file_list.highlighted_child
                        if item:
                            item_id = item.id or ""
                            
                            # Block navigation during file operations
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
                            # Symlinks do nothing on click for now
                    # single click just selects (ListView handles highlight)
                return
            widget = getattr(widget, "parent", None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle action buttons."""
        btn_id = event.button.id
        
        # Block navigation buttons during file operations
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
        """Get the currently selected file entry."""
        file_list = self.query_one("#file-list", ListView)
        idx = file_list.index
        if idx is None:
            return None
        items = list(file_list.children)
        if idx < 0 or idx >= len(items):
            return None
        item = items[idx]
        item_id = item.id or ""
        if item_id == "entry_parent":
            return ("..", True)
        elif item_id.startswith("entry_dir_"):
            safe_name = item_id.removeprefix("entry_dir_")
            original_name = self._id_to_name.get(safe_name, safe_name)
            return (original_name, True)
        elif item_id.startswith("entry_link_"):
            safe_name = item_id.removeprefix("entry_link_")
            original_name = self._id_to_name.get(safe_name, safe_name)
            return (original_name, True)  # Treat links as directories for navigation
        elif item_id.startswith("entry_file_"):
            safe_name = item_id.removeprefix("entry_file_")
            original_name = self._id_to_name.get(safe_name, safe_name)
            return (original_name, False)
        return None

    async def _handle_download(self) -> None:
        """Download selected file/directory to local downloads folder - start worker flow."""
        selected = self._get_selected_file()
        if not selected:
            self.set_status("No file selected")
            return
        
        # Block navigation during operation
        self._operation_in_progress = True
        
        name, is_dir = selected

        remote_path = str(PurePosixPath(self.current_path) / name)
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(downloads, exist_ok=True)
        local_path = os.path.join(downloads, name)

        # Store state for the download process
        self._download_state = DownloadState()
        self._download_state.remote_path = remote_path
        self._download_state.local_path = local_path
        self._download_state.name = name

        # Start the entire download flow in a tracked worker
        self._start_worker("download", self._download_flow(), group="download", exclusive=True)

    async def _download_flow(self) -> None:
        """Worker method that handles entire download flow including modals."""
        # Check for existing file
        self.post_message(ProgressMessage("Download", "Checking remote file", 10))
        exists = await self._file_exists(self._download_state.remote_path)
        if not exists:
            self.post_message(StatusMessage("File not found on remote"))
            self.post_message(ProgressMessage("Download", "Complete", 100))
            return

        # Perform the actual download
        self.post_message(ProgressMessage("Download", "Starting transfer", 20))
        
        # Check if downloading a directory by checking if selection was a directory
        is_dir_download = any(
            entry.name == self._download_state.name and entry.is_dir 
            for entry in self.entries
        )
        
        if is_dir_download:
            # Use recursive SCP for directories
            cmd = f"scp -r -P {self.host.port} -i \"{self.host.ssh_key}\" \"{self.host.user}@{self.host.ip}\":\"{self._download_state.remote_path}\" \"{self._download_state.local_path}\""
        else:
            # Use regular SCP for files
            cmd = self._build_scp_command(
                self._download_state.remote_path, 
                self._download_state.local_path, 
                download=True
            )
        
        try:
            # Use CREATE_NO_WINDOW on Windows to prevent console inheritance
            import sys
            kwargs = {}
            if sys.platform == 'win32':
                kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                **kwargs
            )
            self.post_message(ProgressMessage("Download", "Transferring", 50))
            await proc.communicate()
            
            if proc.returncode == 0:
                self.post_message(ProgressMessage("Download", "Finalizing", 90))
                self.post_message(DownloadCompleteMessage(
                    True, f"Downloaded to Downloads/{self._download_state.name}"
                ))
            else:
                self.post_message(DownloadCompleteMessage(
                    False, "Download failed"
                ))
        except Exception as e:
            self.post_message(DownloadCompleteMessage(
                False, f"Error: {str(e)[:50]}"
            ))

    def on_download_complete_message(self, event: DownloadCompleteMessage) -> None:
        """Handle download completion message from worker."""
        self.set_status(event.message)
        self.hide_progress()
        # Allow navigation again
        self._operation_in_progress = False
        # Remove from tracking without canceling (already finished)
        if "download" in self._active_workers:
            del self._active_workers["download"]
        # No refresh needed for download (local file operation)

    def on_progress_message(self, event: ProgressMessage) -> None:
        """Handle progress updates from workers."""
        if event.percentage is not None:
            self.show_progress(event.percentage)
            self.set_status(f"{event.operation}: {event.stage} ({event.percentage}%)")
        else:
            self.set_status(f"{event.operation}: {event.stage}")

    async def _handle_upload(self) -> None:
        """Upload a local file to current remote directory - start worker to handle modals."""
        # Block navigation during operation
        self._operation_in_progress = True
        self.set_status("Preparing upload...")
        self.show_progress(0)
        # Start worker to handle entire upload flow including modals
        self._start_worker("upload", self._upload_flow_with_modals(), group="upload", exclusive=True)

    async def _upload_flow_with_modals(self) -> None:
        """Worker: Handles entire upload flow including modals and keeps subprocess reference."""
        # Store worker reference for cancellation checks
        worker = get_current_worker()
        
        # Ask for file path
        self.post_message(ProgressMessage("Upload", "Requesting file path"))
        local_path = await self.app.push_screen_wait(_InputModal("Local file path:"))
        if not local_path or not os.path.exists(local_path):
            self.post_message(StatusMessage("File not found or cancelled"))
            self.post_message(UploadCompleteMessage(False, "Cancelled", refresh=False))
            return

        local_name = os.path.basename(local_path)
        remote_path = str(PurePosixPath(self.current_path) / local_name)
        
        # Check if uploading a directory
        is_dir_upload = os.path.isdir(local_path)

        # Check if file/directory exists remotely
        self.post_message(ProgressMessage("Upload", "Checking remote file", 10))
        exists = await self._file_exists(remote_path, timeout=5)
        if exists:
            # Ask for overwrite confirmation
            self.post_message(ProgressMessage("Upload", "Requesting confirmation", 15))
            confirmed = await self.app.push_screen_wait(
                ConfirmModal(f"'{local_name}' exists. Overwrite?")
            )
            if not confirmed:
                self.post_message(StatusMessage("Upload cancelled"))
                self.post_message(UploadCompleteMessage(False, "Cancelled", refresh=False))
                return

        # Perform the actual upload
        self.post_message(ProgressMessage("Upload", "Starting transfer", 20))
        
        if is_dir_upload:
            cmd = f"scp -r -P {self.host.port} -i \"{self.host.ssh_key}\" \"{local_path}\" \"{self.host.user}@{self.host.ip}\":\"{remote_path}\""
        else:
            cmd = self._build_scp_command(remote_path, local_path, download=False)
        
        try:
            import sys
            kwargs = {}
            if sys.platform == 'win32':
                kwargs['creationflags'] = 0x08000000
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                **kwargs
            )
            
            # Store subprocess reference for cancellation
            self._upload_proc = proc
            
            self.post_message(ProgressMessage("Upload", "Transferring", 60))
            await proc.communicate()
            
            # Check if worker was cancelled during transfer
            if worker.is_cancelled:
                try:
                    proc.kill()
                except:
                    pass
                return
            
            if proc.returncode == 0:
                self.post_message(UploadCompleteMessage(True, f"Uploaded {local_name}", refresh=True))
            else:
                self.post_message(UploadCompleteMessage(False, "Upload failed", refresh=False))
        except Exception as e:
            self.post_message(UploadCompleteMessage(False, f"Error: {str(e)[:50]}", refresh=False))

    def on_upload_complete_message(self, event: UploadCompleteMessage) -> None:
        """Handle upload completion message from worker."""
        self.set_status(event.message)
        self.hide_progress()
        # Allow navigation again
        self._operation_in_progress = False
        # Remove from tracking without canceling (already finished)
        if "upload" in self._active_workers:
            del self._active_workers["upload"]
        if event.refresh:
            # Refresh directory listing - start a new worker for this
            self._start_worker("load_directory", self._load_directory(self.current_path))

    def _start_worker(self, name: str, coro, group: str = None, exclusive: bool = False) -> Worker:
        """Start a worker and track it for cancellation."""
        worker = self.run_worker(coro, group=group, exclusive=exclusive)
        self._active_workers[name] = worker
        return worker

    def _cancel_worker(self, name: str) -> None:
        """Cancel a specific worker."""
        if name in self._active_workers:
            worker = self._active_workers[name]
            if not worker.is_cancelled:
                worker.cancel()
            del self._active_workers[name]

    def _cancel_all_workers(self) -> None:
        """Cancel all active workers."""
        for name in list(self._active_workers.keys()):
            self._cancel_worker(name)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Track worker state changes for cleanup."""
        if event.worker.is_finished:
            # Remove finished workers from tracking
            for name, worker in list(self._active_workers.items()):
                if worker == event.worker:
                    del self._active_workers[name]
                    break

    def on_close(self) -> None:
        """Clean up workers when modal is closed."""
        self._cancel_all_workers()

    async def _handle_view(self) -> None:
        """View file contents (read-only preview) - start worker flow."""
        selected = self._get_selected_file()
        if not selected:
            self.set_status("No file selected")
            return
        name, is_dir = selected
        if is_dir:
            self.set_status("Cannot view directories")
            return

        remote_path = str(PurePosixPath(self.current_path) / name)
        self.set_status(f"Loading {name}...")
        
        # Run view operation in a tracked worker
        self._start_worker("view", self._view_flow(remote_path, name), group="view", exclusive=True)

    async def _view_flow(self, remote_path: str, name: str) -> None:
        """Worker method to load file content and show preview."""
        # Use head to limit size for preview
        self.post_message(ProgressMessage("View", "Loading file content"))
        cmd = self._build_ssh_command(f'head -c 50000 "{remote_path}"')
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.post_message(ProgressMessage("View", "Reading", 50))
            stdout, stderr = await proc.communicate()
            
            # Sanitize any output before processing
            if stderr:
                stderr_clean = _strip_ansi(stderr.decode().strip())
                if stderr_clean:
                    self.post_message(StatusMessage(f"View warning: {stderr_clean[:50]}"))
            
            if proc.returncode == 0:
                content = stdout.decode('utf-8', errors='replace')
                content = _strip_ansi(content)  # Ensure content is clean
                self.post_message(ProgressMessage("View", "Finalizing", 90))
                self.post_message(StatusMessage(f"Loaded {name}"))
                # Show preview from UI thread
                await self._show_preview(name, content)
            else:
                self.post_message(StatusMessage("Failed to read file"))
        except Exception as e:
            self.post_message(StatusMessage(f"Error: {str(e)[:50]}"))

    async def _handle_delete(self) -> None:
        """Delete selected remote file/directory - start worker flow."""
        selected = self._get_selected_file()
        if not selected:
            self.set_status("No file selected")
            return
        
        # Block navigation during operation
        self._operation_in_progress = True
        name, is_dir = selected
        if name == "..":
            self.set_status("Cannot delete parent directory")
            return

        remote_path = str(PurePosixPath(self.current_path) / name)

        # Store state for the delete process
        self._delete_state = DeleteState()
        self._delete_state.remote_path = remote_path
        self._delete_state.name = name
        self._delete_state.is_dir = is_dir

        # Start the entire delete flow in a tracked worker
        self._start_worker("delete", self._delete_flow(), group="delete", exclusive=True)

    async def _delete_flow(self) -> None:
        """Worker method that handles the entire delete flow including modal."""
        # Ask for confirmation
        self.post_message(ProgressMessage("Delete", "Requesting confirmation", 10))
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(f"Delete '{self._delete_state.name}'? This cannot be undone.")
        )
        if not confirmed:
            self.post_message(StatusMessage("Delete cancelled"))
            self.post_message(ProgressMessage("Delete", "Cancelled", 100))
            return

        # Perform the actual delete
        self.post_message(ProgressMessage("Delete", "Removing file", 30))
        rm_cmd = "rm -rf" if self._delete_state.is_dir else "rm"
        cmd = self._build_ssh_command(f'{rm_cmd} "{self._delete_state.remote_path}"')
        try:
            # Use CREATE_NO_WINDOW on Windows to prevent console inheritance
            import sys
            kwargs = {}
            if sys.platform == 'win32':
                kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                **kwargs
            )
            self.post_message(ProgressMessage("Delete", "Executing", 70))
            await proc.communicate()
            
            if proc.returncode == 0:
                self.post_message(ProgressMessage("Delete", "Finalizing", 90))
                self.post_message(DeleteCompleteMessage(
                    True, f"Deleted {self._delete_state.name}", refresh=True
                ))
            else:
                self.post_message(DeleteCompleteMessage(
                    False, "Delete failed", refresh=True
                ))
        except Exception as e:
            self.post_message(DeleteCompleteMessage(
                False, f"Error: {str(e)[:50]}", refresh=True
            ))

    def on_delete_complete_message(self, event: DeleteCompleteMessage) -> None:
        """Handle delete completion message from worker."""
        self.set_status(event.message)
        self.hide_progress()
        # Allow navigation again
        self._operation_in_progress = False
        # Remove from tracking without canceling (already finished)
        if "delete" in self._active_workers:
            del self._active_workers["delete"]
        if event.refresh:
            # Refresh directory listing
            self._start_worker("load_directory", self._load_directory(self.current_path))

    async def _file_exists(self, remote_path: str, timeout: int = 10) -> bool:
        """Check if a remote file exists with timeout."""
        cmd = self._build_ssh_command(f'test -e "{remote_path}" && echo yes || echo no')
        try:
            # Use CREATE_NO_WINDOW on Windows to prevent console inheritance
            import sys
            kwargs = {}
            if sys.platform == 'win32':
                kwargs['creationflags'] = 0x08000000  # CREATE_NO_WINDOW
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs
            )
            # Add timeout to prevent hanging
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            
            # Sanitize both stdout and stderr before processing
            result = _strip_ansi(stdout.decode().strip()) if stdout else ""
            stderr_clean = _strip_ansi(stderr.decode().strip()) if stderr else ""
            
            # Ignore stderr - don't print or show in UI
            return result == "yes"
        except asyncio.TimeoutError:
            # Kill the process if it timed out
            try:
                proc.kill()
            except:
                pass
            return False
        except Exception:
            return False

    async def _show_preview(self, filename: str, content: str) -> None:
        """Show file preview modal."""
        await self.push_screen(_PreviewModal(filename, content))

    def set_status(self, message: str) -> None:
        """Update status bar."""
        self.query_one("#status-bar", Label).update(message)

    def show_progress(self, value: int = 0) -> None:
        """Show progress bar with given value."""
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.update(progress=value)
        progress_bar.add_class("visible")

    def hide_progress(self) -> None:
        """Hide progress bar."""
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.remove_class("visible")


class _InputModal(ModalScreen):
    """Simple input modal for user prompts."""

    CSS = """
    _InputModal { align: center middle; }
    #input-box {
        width: 60;
        height: auto;
        background: $surface;
        border: tall $primary;
        padding: 1 2;
    }
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
            value = self.query_one("#input-field", Input).value
            self.dismiss(value if value else None)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ok":
            value = self.query_one("#input-field", Input).value
            self.dismiss(value if value else None)
        else:
            self.dismiss(None)


class _PreviewModal(ModalScreen):
    """Modal for viewing file contents."""

    CSS = """
    _PreviewModal { align: center middle; }
    #preview-box {
        width: 85;
        height: 85%;
        background: $surface;
        border: tall $primary;
        padding: 1 2;
    }
    #preview-title { height: 1; color: $accent; margin-bottom: 1; }
    #preview-content {
        height: 1fr;
        border: solid $primary;
        background: $surface-darken-1;
        padding: 1;
        overflow: auto;
    }
    #preview-footer { height: 3; margin-top: 1; }
    """

    def __init__(self, filename: str, content: str) -> None:
        super().__init__()
        self.filename = filename
        # Limit displayed content
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
