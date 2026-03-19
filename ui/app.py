"""
Main Textual UI application.
Panels: left = server groups, right = hosts.
Features: search (/ or s), port forwarding modal, refresh (r).
"""
from __future__ import annotations
import asyncio
from typing import List, Dict
from textual.app import App, ComposeResult
from textual.widgets import ListView, ListItem, Label, Header, Footer, Input, Checkbox, Button
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.binding import Binding

from inventory.loader import Host, load_server_types, get_hosts
from inventory.cache import build_cache, refresh_cache
from ui.search import filter_hosts, filter_groups
from ssh.connection import open_ssh_terminal, build_ssh_command
from utils.logger import log_login
from constants import DEFAULT_PORTS

# Two status dicts, one per test type
# ping  → ICMP-style: try TCP on port 22 as proxy (pure Python, no root needed)
# telnet → TCP connect to the host's actual configured port
_COL = {"status": 2, "name": 30, "ip": 18, "user": 12, "port": 6}
_HEADER = (
    f"{'P':2}  "
    f"{'T':2}  "
    f"{'Name':<30}  "
    f"{'IP':<18}  "
    f"{'User':<12}  "
    f"Port"
)

async def _check_reachable(ip: str, port: int, timeout: float = 2.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Port Forwarding Modal
# ---------------------------------------------------------------------------
class ForwardingModal(ModalScreen):
    """Modal to pick port forwards before connecting."""

    CSS = """
    ForwardingModal {
        align: center middle;
    }
    #modal-box {
        width: 60;
        height: auto;
        background: $surface;
        border: tall $primary;
        padding: 1 2;
    }
    #custom-input {
        margin-top: 1;
    }
    #modal-footer {
        margin-top: 1;
    }
    """

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Label(f"Port Forwarding  —  {self.host.name} ({self.host.ip})")
            yield Label("Select presets (LOCAL:REMOTE):")
            for p in DEFAULT_PORTS:
                yield Checkbox(p["label"], value=False, id=f"preset_{p['local']}_{p['remote']}")
            yield Label("Custom forwards (LOCAL:REMOTE, comma separated):")
            yield Input(placeholder="e.g. 8081:80,5433:5432", id="custom-input")
            yield Button("Connect", variant="primary", id="btn-connect")
            yield Label("ENTER / Click Connect → SSH    ESC → Cancel", id="modal-footer")

    def on_key(self, event) -> None:
        if event.key == "enter":
            self._connect()
            event.stop()
        elif event.key == "escape":
            self.dismiss(None)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-connect":
            self._connect()

    def _connect(self) -> None:
        forwards: List[str] = []
        for p in DEFAULT_PORTS:
            cb = self.query_one(f"#preset_{p['local']}_{p['remote']}", Checkbox)
            if cb.value:
                forwards.append(f"{p['local']}:{p['remote']}")
        custom_raw = self.query_one("#custom-input", Input).value.strip()
        if custom_raw:
            for part in custom_raw.split(","):
                part = part.strip()
                if ":" in part:
                    forwards.append(part)
        self.dismiss(forwards)


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------
class InventoryApp(App):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("/", "search", "Search"),
        Binding("f", "forwarding", "Forwarding"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    CSS = """
    Screen { layout: horizontal; }
    #left-panel { width: 30%; border-right: solid $primary; }
    #right-panel { width: 70%; }
    #search-bar { dock: top; display: none; }
    #search-row { height: 3; display: none; }
    #host-search-bar { width: 1fr; }
    #btn-ping { min-width: 8; width: 8; }
    #btn-telnet { min-width: 9; width: 9; }
    #host-header-row { height: 1; background: $boost; padding: 0 1; display: none; }
    #host-header { color: $text-muted; }
    ListView { height: 1fr; }
    Footer { height: 3; }
    """

    def __init__(self) -> None:
        super().__init__()
        build_cache()
        self._server_types: List[str] = list(load_server_types().keys())
        self._current_type: str = ""
        self._all_hosts: List[Host] = []
        self._ping_status: Dict[str, str] = {}    # TCP/22 reachability
        self._telnet_status: Dict[str, str] = {}  # TCP/configured port

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="left-panel"):
                yield Input(placeholder="Filter groups...", id="search-bar")
                yield ListView(
                    *[ListItem(Label(t), id=f"grp_{t}") for t in self._server_types],
                    id="group-list",
                )
            with Vertical(id="right-panel"):
                with Horizontal(id="search-row"):
                    yield Input(placeholder="Search hosts...", id="host-search-bar")
                    yield Button("Ping", id="btn-ping", variant="default")
                    yield Button("Telnet", id="btn-telnet", variant="default")
                with Horizontal(id="host-header-row"):
                    yield Label(_HEADER, id="host-header")
                yield ListView(id="host-list")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#search-row", Horizontal).display = False
        self.query_one("#host-header-row", Horizontal).display = False

    # ------------------------------------------------------------------
    # Group selection only — host actions handled by on_key / on_click
    # ------------------------------------------------------------------
    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "group-list":
            item_id: str = event.item.id or ""
            self._current_type = item_id.removeprefix("grp_")
            self._all_hosts = get_hosts(self._current_type)
            self._ping_status = {}
            self._telnet_status = {}
            await self._render_hosts(self._all_hosts)
            bar = self.query_one("#host-search-bar", Input)
            bar.value = ""
            self.query_one("#search-row", Horizontal).display = True
            self.query_one("#host-header-row", Horizontal).display = True
            self.query_one("#host-list", ListView).focus()
        # host-list selection intentionally ignored here

    async def on_key(self, event) -> None:
        if event.key == "enter":
            # Only act if host list is focused
            host_list = self.query_one("#host-list", ListView)
            if self.focused is host_list:
                host = self._focused_host()
                if host:
                    event.stop()
                    await self._connect_direct(host)

    async def on_click(self, event) -> None:
        # Ignore clicks when a modal screen is active
        if len(self.screen_stack) > 1:
            return
        host_list = self.query_one("#host-list", ListView)
        # Check if click landed anywhere inside the host list tree
        widget = event.widget
        while widget is not None:
            if widget is host_list:
                host = self._focused_host()
                if not host:
                    return
                if event.button == 1:
                    await self._connect_direct(host)
                elif event.button == 3:
                    await self._open_forwarding(host)
                return
            widget = getattr(widget, 'parent', None)

    async def action_forwarding(self) -> None:
        host = self._focused_host()
        if host:
            await self._open_forwarding(host)

    def _focused_host(self) -> Host | None:
        host_list = self.query_one("#host-list", ListView)
        idx = host_list.index
        visible = self._visible_hosts()
        if idx is not None and 0 <= idx < len(visible):
            return visible[idx]
        return None

    async def _connect_direct(self, host: Host) -> None:
        """Log and launch SSH with no forwards. List stays populated."""
        log_login(host)
        open_ssh_terminal(host, [])

    def _visible_hosts(self) -> List[Host]:
        bar = self.query_one("#host-search-bar", Input)
        return filter_hosts(self._all_hosts, bar.value)

    async def _render_hosts(self, hosts: List[Host]) -> None:
        host_list = self.query_one("#host-list", ListView)
        await host_list.clear()
        for h in hosts:
            p = self._ping_status.get(h.name, "[dim]--[/dim]")
            t = self._telnet_status.get(h.name, "[dim]--[/dim]")
            label = f"{p}  {t}  {h.name:<30}  {h.ip:<18}  {h.user:<12}  {h.port}"
            await host_list.append(ListItem(Label(label, markup=True), id=f"host_{h.name}"))

    # ------------------------------------------------------------------
    # Live search on host bar
    # ------------------------------------------------------------------
    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "host-search-bar":
            filtered = filter_hosts(self._all_hosts, event.value)
            await self._render_hosts(filtered)
        elif event.input.id == "search-bar":
            filtered_groups = filter_groups(self._server_types, event.value)
            group_list = self.query_one("#group-list", ListView)
            await group_list.clear()
            for t in filtered_groups:
                await group_list.append(ListItem(Label(t), id=f"grp_{t}"))

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in either search bar moves focus to the relevant list."""
        if event.input.id == "host-search-bar":
            self.query_one("#host-list", ListView).focus()
        elif event.input.id == "search-bar":
            self.query_one("#group-list", ListView).focus()

    # ------------------------------------------------------------------
    # Port forwarding modal
    # ------------------------------------------------------------------
    async def _open_forwarding(self, host: Host) -> None:
        async def on_dismiss(forwards) -> None:
            if forwards is None:
                return
            log_login(host)
            open_ssh_terminal(host, forwards)

        await self.push_screen(ForwardingModal(host), on_dismiss)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    async def action_back(self) -> None:
        host_list = self.query_one("#host-list", ListView)
        await host_list.clear()
        self._all_hosts = []
        self._current_type = ""
        self._ping_status = {}
        self._telnet_status = {}
        bar = self.query_one("#host-search-bar", Input)
        bar.value = ""
        self.query_one("#search-row", Horizontal).display = False
        self.query_one("#host-header-row", Horizontal).display = False
        self.query_one("#group-list", ListView).focus()

    async def action_refresh(self) -> None:
        refresh_cache()
        self._server_types = list(load_server_types().keys())
        group_list = self.query_one("#group-list", ListView)
        await group_list.clear()
        for t in self._server_types:
            await group_list.append(ListItem(Label(t), id=f"grp_{t}"))
        if self._current_type:
            self._all_hosts = get_hosts(self._current_type)
            await self._render_hosts(self._all_hosts)

    def action_search(self) -> None:
        bar = self.query_one("#host-search-bar", Input)
        if bar.display:
            bar.focus()
        else:
            search_bar = self.query_one("#search-bar", Input)
            search_bar.display = True
            search_bar.focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-ping":
            await self._run_test("ping")
        elif event.button.id == "btn-telnet":
            await self._run_test("telnet")

    async def _run_test(self, mode: str) -> None:
        if not self._all_hosts:
            return
        btn_id = "btn-ping" if mode == "ping" else "btn-telnet"
        btn = self.query_one(f"#{btn_id}", Button)
        btn.disabled = True
        btn.label = "..."

        async def test_one(host: Host) -> None:
            # ping mode: TCP to port 22 (SSH probe)
            # telnet mode: TCP to the host's configured port
            port = 22 if mode == "ping" else host.port
            ok = await _check_reachable(host.ip, port)
            result = "[green]OK[/green]" if ok else "[red]XX[/red]"
            if mode == "ping":
                self._ping_status[host.name] = result
            else:
                self._telnet_status[host.name] = result

        await asyncio.gather(*[test_one(h) for h in self._all_hosts])
        await self._render_hosts(self._visible_hosts())
        btn.label = "Ping" if mode == "ping" else "Telnet"
        btn.disabled = False

