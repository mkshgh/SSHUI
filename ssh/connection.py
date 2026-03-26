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


def _open_linux(ssh_cmd: str) -> None:
    """Try tab-capable terminals first, fall back to any available terminal."""
    tab_attempts = [
        ["gnome-terminal", "--tab", "--", "bash", "-c", f"{ssh_cmd}; exec bash"],
        ["xfce4-terminal", "--tab", "--command", ssh_cmd],
        ["konsole", "--new-tab", "-e", ssh_cmd],
        ["tilix", "--action=app-new-session", "-e", ssh_cmd],
    ]
    window_fallbacks = [
        ["x-terminal-emulator", "-e", ssh_cmd],
        ["xterm", "-e", ssh_cmd],
    ]
    for cmd in tab_attempts + window_fallbacks:
        try:
            subprocess.Popen(cmd)
            return
        except FileNotFoundError:
            continue


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
