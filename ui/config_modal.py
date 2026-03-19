"""
Config modal — default port forwards only.
Theme is managed via the command palette (Ctrl+P) and saved automatically.
"""
from __future__ import annotations
from typing import List, Dict, Any
from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Label, Input, Checkbox, Button
from textual.containers import Horizontal, Vertical, ScrollableContainer

from constants import DEFAULT_PORTS


class ConfigModal(ModalScreen):

    CSS = """
    ConfigModal { align: center middle; }
    #cfg-box {
        width: 64;
        height: auto;
        max-height: 36;
        background: $surface;
        border: tall $primary;
        padding: 1 2;
    }
    #cfg-ports-scroll { height: auto; max-height: 20; }
    #cfg-custom { margin-top: 1; }
    #cfg-btn-row { height: 3; margin-top: 1; align: right middle; }
    #cfg-btn-save { min-width: 10; }
    #cfg-btn-cancel { min-width: 10; margin-left: 1; }
    .section-title { color: $accent; margin-top: 1; }
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        default_fwd_set = set(self._config.get("default_forwards", []))
        preset_keys = {f"{p['local']}:{p['remote']}" for p in DEFAULT_PORTS}
        custom_existing = [f for f in default_fwd_set if f not in preset_keys]

        with Vertical(id="cfg-box"):
            yield Label("Default Port Forwards", classes="section-title")
            yield Label("Pre-checked automatically for every SSH connection:")
            with ScrollableContainer(id="cfg-ports-scroll"):
                for p in DEFAULT_PORTS:
                    key = f"{p['local']}:{p['remote']}"
                    yield Checkbox(
                        p["label"],
                        value=(key in default_fwd_set),
                        id=f"cfg_preset_{p['local']}_{p['remote']}",
                    )
                yield Label("Custom (LOCAL:REMOTE, comma separated):")
                yield Input(
                    value=", ".join(custom_existing),
                    placeholder="e.g. 8082:8080,5433:5432",
                    id="cfg-custom",
                )
            yield Label("[dim]Tip: change theme via Ctrl+P → Change theme[/dim]", markup=True)
            with Horizontal(id="cfg-btn-row"):
                yield Button("Save", variant="primary", id="cfg-btn-save")
                yield Button("Cancel", id="cfg-btn-cancel")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cfg-btn-save":
            self._save()
        elif event.button.id == "cfg-btn-cancel":
            self.dismiss(None)

    def _save(self) -> None:
        forwards: List[str] = []
        for p in DEFAULT_PORTS:
            cb = self.query_one(f"#cfg_preset_{p['local']}_{p['remote']}", Checkbox)
            if cb.value:
                forwards.append(f"{p['local']}:{p['remote']}")
        custom_raw = self.query_one("#cfg-custom", Input).value.strip()
        if custom_raw:
            for part in custom_raw.split(","):
                part = part.strip()
                if ":" in part:
                    forwards.append(part)
        self.dismiss({"forwards": forwards})
