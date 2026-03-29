"""
Loads and parses YAML inventory files from the .conf cache.
Returns normalized Host dataclass objects.
"""
import csv
import yaml
from dataclasses import dataclass
from typing import List, Dict
from constants import CSV_FILE
from inventory.cache import get_cached_path


@dataclass
class Host:
    name: str
    ip: str
    user: str
    port: int
    password: str
    ssh_key: str = ""
    server_type: str = ""


def load_server_types() -> Dict[str, str]:
    """Return {server_type: cached_yaml_path} from CSV, sorted case-insensitively."""
    data: Dict[str, str] = {}
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            st = row["server_type"].strip()
            data[st] = get_cached_path(st)
    return dict(sorted(data.items(), key=lambda x: x[0].lower()))


def get_host_count(server_type: str) -> int:
    """Return the number of hosts in a server_type's cached YAML."""
    return len(get_hosts(server_type))


def get_hosts(server_type: str) -> List[Host]:
    """Parse hosts from the cached YAML for a given server_type.
    The top-level YAML key (yaml_header) is auto-detected as the first key
    in the file, regardless of whether it matches server_type.
    """
    path = get_cached_path(server_type)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (FileNotFoundError, yaml.YAMLError):
        return []

    if not data:
        return []

    # Use the first top-level key as yaml_header
    yaml_header = next(iter(data))
    group_data = data.get(yaml_header, {}) or {}
    hosts_data = group_data.get("hosts", {}) or {}
    hosts: List[Host] = []
    for name, vars_ in hosts_data.items():
        vars_ = vars_ or {}
        hosts.append(Host(
            name=name,
            ip=vars_.get("ansible_host", name),
            user=vars_.get("ansible_user", "root"),
            port=int(vars_.get("ansible_port", 22)),
            password=vars_.get("ansible_password", ""),
            ssh_key=vars_.get("ansible_ssh_private_key_file", ""),
            server_type=server_type,
        ))
    return hosts
