"""SSH login logger."""
import datetime
from constants import LOG_FILE
from inventory.loader import Host


def log_login(host: Host) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{now} | {host.server_type} | {host.name} | {host.user}@{host.ip}:{host.port}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line)
