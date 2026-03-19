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
        subprocess.Popen(["cmd", "/c", "start", "powershell", "-NoExit", "-Command", ssh_cmd])
    elif system == "Linux":
        for term in ["x-terminal-emulator", "gnome-terminal", "xterm"]:
            try:
                subprocess.Popen([term, "-e", ssh_cmd])
                return
            except FileNotFoundError:
                continue
    elif system == "Darwin":
        script = f'tell app "Terminal" to do script "{ssh_cmd}"'
        subprocess.Popen(["osascript", "-e", script])
