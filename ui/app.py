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

from inventory.loader import Host, load_server_types, get_hosts, get_host_count
from inventory.cache import build_cache, refresh_cache
from ui.search import filter_hosts, filter_groups
from ui.config_modal import ConfigModal
from ssh.connection import open_ssh_terminal, build_ssh_command
from utils.logger import log_login
from utils.config import load_config, save_config
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
    f"{'Port':<6}  "
    f"Defaults"
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
    ForwardingModal { align: center middle; }
    #modal-box {
        width: 80;
        height: auto;
        background: $surface;
        border: tall $primary;
        padding: 1 2;
    }
    #fwd-presets-grid { layout: grid; grid-size: 2; grid-gutter: 0 1; height: auto; }
    #fwd-custom-grid  { layout: grid; grid-size: 2; grid-gutter: 0 1; height: auto; }
    #custom-input { margin-top: 1; }
    #modal-footer { margin-top: 1; }
    """

    def __init__(self, host: Host, default_forwards: List[str] = None) -> None:
        super().__init__()
        self.host = host
        all_defaults = default_forwards or []
        preset_keys = {f"{p['local']}:{p['remote']}" for p in DEFAULT_PORTS}
        self._default_forwards = set(all_defaults)
        # custom = defaults that aren't in the built-in preset list
        self._custom_defaults = [f for f in all_defaults if f not in preset_keys]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Label(f"Port Forwarding  —  {self.host.name} ({self.host.ip})")
            yield Label("Presets:")
            with Horizontal(id="fwd-presets-grid"):
                for p in DEFAULT_PORTS:
                    key = f"{p['local']}:{p['remote']}"
                    yield Checkbox(
                        p["label"],
                        value=(key in self._default_forwards),
                        id=f"preset_{p['local']}_{p['remote']}",
                    )
            if self._custom_defaults:
                yield Label("Custom defaults:")
                with Horizontal(id="fwd-custom-grid"):
                    for fwd in self._custom_defaults:
                        yield Checkbox(
                            fwd,
                            value=True,
                            id=f"custom_def_{fwd.replace(':', '_')}",
                        )
            yield Label("Additional forwards (LOCAL:REMOTE, comma separated):")
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
        # preset checkboxes
        for p in DEFAULT_PORTS:
            cb = self.query_one(f"#preset_{p['local']}_{p['remote']}", Checkbox)
            if cb.value:
                forwards.append(f"{p['local']}:{p['remote']}")
        # custom default checkboxes
        for fwd in self._custom_defaults:
            cb = self.query_one(f"#custom_def_{fwd.replace(':', '_')}", Checkbox)
            if cb.value:
                forwards.append(fwd)
        # additional one-off input
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
        Binding("escape", "back", "Back", show=True),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("/", "search", "Search"),
        Binding("f", "forwarding", "Forwarding", priority=True),
        Binding("ctrl+y", "noop", "Yank pwd", show=True),
        Binding("ctrl+g", "config", "Config", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
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
        self._config = load_config()
        build_cache()
        self._server_types: List[str] = list(load_server_types().keys())
        self._current_type: str = ""
        self._all_hosts: List[Host] = []
        self._ping_status: Dict[str, str] = {}
        self._telnet_status: Dict[str, str] = {}

    def _group_label(self, server_type: str) -> str:
        count = get_host_count(server_type)
        return f"{server_type} ({count})"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="left-panel"):
                yield Input(placeholder="Filter groups...", id="search-bar")
                yield ListView(
                    *[ListItem(Label(self._group_label(t)), id=f"grp_{t}") for t in self._server_types],
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

    def watch_theme(self, theme: str) -> None:
        """Auto-save theme to config whenever it changes (e.g. via command palette)."""
        self._config["theme"] = theme
        save_config(self._config)

    def on_mount(self) -> None:
        theme = self._config.get("theme", "textual-dark")
        registered = list(self._registered_themes.keys()) if hasattr(self, "_registered_themes") else []
        if theme in registered:
            self.theme = theme
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
            await self._render_hosts(self._visible_hosts())
            bar = self.query_one("#host-search-bar", Input)
            bar.value = ""
            self.query_one("#search-row", Horizontal).display = True
            self.query_one("#host-header-row", Horizontal).display = True
            self.query_one("#host-list", ListView).focus()
        # host-list selection intentionally ignored here

    async def _on_key(self, event) -> None:
        """Fires before any widget — used for truly global shortcuts."""
        if event.key == "escape":
            if len(self.screen_stack) == 1:
                await self.action_back()
                event.stop()
                event.prevent_default()
            # if a modal is open, let the modal handle its own ESC
            return
        if event.key == "ctrl+g":
            await self.action_config()
            event.stop()
            event.prevent_default()
        elif event.key == "ctrl+y":
            # Yank (copy) password of focused host to clipboard
            host = self._focused_host()
            if host and host.password:
                try:
                    import pyperclip
                    pyperclip.copy(host.password)
                except Exception:
                    pass
                event.stop()
                event.prevent_default()
        elif event.key == "enter":
            # Handle Enter for host list here — before ListView consumes it
            if len(self.screen_stack) == 1:  # not in a modal
                host_list = self.query_one("#host-list", ListView)
                w = self.focused
                while w is not None:
                    if w is host_list:
                        host = self._focused_host()
                        if host:
                            event.stop()
                            event.prevent_default()
                            await self._connect_direct(host)
                        return
                    w = getattr(w, "parent", None)

    async def on_key(self, event) -> None:
        pass  # all key handling in _on_key

    async def on_click(self, event) -> None:
        if len(self.screen_stack) > 1:
            return
        host_list = self.query_one("#host-list", ListView)
        widget = event.widget
        while widget is not None:
            if widget is host_list:
                host = self._focused_host()
                if not host:
                    return
                if event.button == 3:
                    await self._open_forwarding(host)
                elif event.button == 1:
                    import time
                    now = time.monotonic()
                    last = getattr(self, "_last_click_time", 0)
                    self._last_click_time = now
                    if now - last < 0.4:  # double-click threshold
                        self._last_click_time = 0
                        await self._connect_direct(host)
                    # single click just selects (ListView handles highlight)
                return
            widget = getattr(widget, "parent", None)

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
        """Log and launch SSH. Uses default forwards from config if set."""
        log_login(host)
        forwards = self._config.get("default_forwards", [])
        open_ssh_terminal(host, forwards)

    def _visible_hosts(self) -> List[Host]:
        bar = self.query_one("#host-search-bar", Input)
        hosts = filter_hosts(self._all_hosts, bar.value)
        return sorted(hosts, key=lambda h: h.name.lower())

    async def _render_hosts(self, hosts: List[Host]) -> None:
        host_list = self.query_one("#host-list", ListView)
        await host_list.clear()
        default_fwds = self._config.get("default_forwards", [])
        fwd_tag = (" [" + " ".join(f.split(":")[0] for f in default_fwds) + "]") if default_fwds else ""
        for h in hosts:
            p = self._ping_status.get(h.name, "[dim]--[/dim]")
            t = self._telnet_status.get(h.name, "[dim]--[/dim]")
            label = f"{p}  {t}  {h.name:<30}  {h.ip:<18}  {h.user:<12}  {h.port:<6}  [dim]{fwd_tag.strip()}[/dim]"
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
                await group_list.append(ListItem(Label(self._group_label(t)), id=f"grp_{t}"))

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

        await self.push_screen(
            ForwardingModal(host, self._config.get("default_forwards", [])),
            on_dismiss,
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    async def action_back(self) -> None:
        # Don't clear host list if a modal is being dismissed
        if len(self.screen_stack) > 1:
            return
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
            await group_list.append(ListItem(Label(self._group_label(t)), id=f"grp_{t}"))
        if self._current_type:
            self._all_hosts = get_hosts(self._current_type)
            await self._render_hosts(self._visible_hosts())

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

    async def action_config(self) -> None:
        async def on_dismiss(result) -> None:
            if result is None:
                return
            self._config["default_forwards"] = result["forwards"]
            save_config(self._config)
            if self._all_hosts:
                await self._render_hosts(self._visible_hosts())

        await self.push_screen(ConfigModal(self._config), on_dismiss)

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


    def action_noop(self) -> None:
        pass
