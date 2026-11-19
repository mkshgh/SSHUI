"""
SSH command builder and terminal launcher.
Supports port forwarding with multiple -L flags.
"""
import platform
import subprocess
from typing import List
from inventory.loader import Host

def build_ssh_command(host: Host, forwards: List[str]) -> str:
    parts = ["ssh"]
    for fwd in forwards:
        local, remote = fwd.split(":", 1)
        parts.append(f"-L {local}:localhost:{remote}")
    if host.ssh_key:
        parts.append(f"-i {host.ssh_key}")
    parts.append(f"{host.user}@{host.ip}")
    parts.append(f"-p {host.port}")
    return " ".join(parts)


def _build_forward_flags(forwards: List[str]) -> str:
    flags = []
    for fwd in forwards:
        local, remote = fwd.split(":", 1)
        flags.append(f"-L {local}:localhost:{remote}")
    return " ".join(flags)


def open_ssh_terminal(host: Host, forwards: List[str]) -> None:
    """Launch SSH in a new terminal window."""
    import pyperclip

    fwd_flags = _build_forward_flags(forwards)

    if host.ssh_key:
        # Key-based auth — no password needed
        ssh_cmd = f"ssh {fwd_flags} -i {host.ssh_key} {host.user}@{host.ip} -p {host.port}"
    else:
        # Password auth — copy to clipboard
        if host.password:
            try:
                pyperclip.copy(host.password)
            except Exception:
                pass
        ssh_cmd = f"ssh {fwd_flags} {host.user}@{host.ip} -p {host.port}"

    ssh_cmd = " ".join(ssh_cmd.split())  # collapse extra spaces

    system = platform.system()
    if system == "Windows":
        _open_windows(ssh_cmd)
    elif system == "Linux":
        _open_linux(ssh_cmd)
    elif system == "Darwin":
        _open_macos(ssh_cmd)


def _open_windows(ssh_cmd: str) -> None:
    """Try Windows Terminal new tab, fall back to a new PowerShell window."""
    try:
        # wt (Windows Terminal) — opens in a new tab of the existing window
        subprocess.Popen(["wt", "--window", "0", "new-tab", "powershell", "-NoExit", "-Command", ssh_cmd])
    except FileNotFoundError:
        # Fallback: plain PowerShell window
        subprocess.Popen(["cmd", "/c", "start", "powershell", "-NoExit", "-Command", ssh_cmd])

import os
import shlex
import shutil
import subprocess


def _open_linux(ssh_cmd: str) -> None:
    """Detect the current terminal and open SSH in an existing window tab."""

    shell = f"{ssh_cmd}; exec bash -i"

    terminals = {
        "ptyxis": ["ptyxis", "--tab", "--"],
        "gnome-terminal": ["gnome-terminal", "--tab", "--"],
        "konsole": ["konsole", "--new-tab", "-e"],
        "xfce4-terminal": ["xfce4-terminal", "--tab", "--command"],
        "mate-terminal": ["mate-terminal", "--tab", "--"],
        "terminator": ["terminator", "--new-tab", "-x"],
        "kitty": ["kitty", "@", "launch", "--type=tab"],
        "wezterm": ["wezterm", "cli", "spawn"],
    }

    # Detect terminal from environment.
    terminal = None

    env_detection = {
        "WEZTERM_PANE": "wezterm",
        "KITTY_WINDOW_ID": "kitty",
        "TILIX_ID": "tilix",
        "GNOME_TERMINAL_SCREEN": "gnome-terminal",
    }

    for variable, name in env_detection.items():
        if os.environ.get(variable):
            terminal = name
            break

    # Detect terminal from parent process tree.
    if not terminal:
        pid = os.getpid()

        for _ in range(20):
            try:
                with open(f"/proc/{pid}/comm") as f:
                    name = f.read().strip().lower()

                if name in ("ptyxis", "ptyxis-agent"):
                    terminal = "ptyxis"
                    break

                if name in ("gnome-terminal-server",):
                    terminal = "gnome-terminal"
                    break

                if name in terminals:
                    terminal = name
                    break

                with open(f"/proc/{pid}/stat") as f:
                    stat = f.read()

                pid = int(stat.rsplit(")", 1)[1].split()[1])

                if pid <= 1:
                    break

            except (OSError, ValueError, IndexError):
                break

    # Ubuntu 25.10+ / 26.04 default terminal.
    if not terminal and shutil.which("ptyxis"):
        terminal = "ptyxis"

    if terminal not in terminals:
        raise RuntimeError(
            f"Cannot identify a supported terminal (detected: {terminal})"
        )

    if not shutil.which(terminal):
        raise RuntimeError(f"Terminal executable not found: {terminal}")

    command = terminals[terminal] + ["bash", "-lc", shell]

    subprocess.Popen(command)

def _open_macos(ssh_cmd: str) -> None:
    """Try a new tab in the front Terminal window, fall back to a new window."""
    # Escape double quotes inside the ssh command for AppleScript
    escaped = ssh_cmd.replace('"', '\\"')
    tab_script = (
        'tell application "Terminal"\n'
        '  if (count of windows) > 0 then\n'
        f'    tell application "System Events" to keystroke "t" using command down\n'
        f'    do script "{escaped}" in front window\n'
        '  else\n'
        f'    do script "{escaped}"\n'
        '  end if\n'
        'end tell'
    )
    subprocess.Popen(["osascript", "-e", tab_script])
