"""
Manages the .conf cache folder.
Copies inventory YAML files from CSV paths, strips comments, never touches originals.
Hosts within each group are sorted A-Z (case-insensitive) at write time.
"""
import os
import shutil
import csv
import yaml
from constants import CSV_FILE, CONF_DIR


def _uncomment_lines(text: str) -> str:
    """Uncomment lines that start with # — preserve indentation, keep content."""
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            indent = line[: len(line) - len(stripped)]
            uncommented = stripped[1:]
            if uncommented.startswith(" "):
                uncommented = uncommented[1:]
            lines.append(indent + uncommented)
        else:
            lines.append(line)
    return "\n".join(lines)


def _sort_hosts_in_data(data: dict) -> dict:
    """Sort the hosts dict inside each top-level group, case-insensitively."""
    if not data:
        return data
    for header, group in data.items():
        if not isinstance(group, dict):
            continue
        hosts = group.get("hosts")
        if isinstance(hosts, dict):
            group["hosts"] = dict(sorted(hosts.items(), key=lambda x: x[0].lower()))
    return data


def _cached_name(server_type: str) -> str:
    return os.path.join(CONF_DIR, f"{server_type}.yaml")


def build_cache() -> None:
    """Create .conf dir and copy cleaned inventories into it."""
    os.makedirs(CONF_DIR, exist_ok=True)
    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            server_type = row["server_type"].strip()
            src_path = os.path.normpath(row["path"].strip())
            dst_path = _cached_name(server_type)
            if not os.path.isfile(src_path):
                continue
            with open(src_path, "r", encoding="utf-8") as src:
                content = src.read()
            cleaned = _uncomment_lines(content)
            try:
                data = yaml.safe_load(cleaned)
                data = _sort_hosts_in_data(data)
                cleaned = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
            except Exception:
                pass  # if YAML parse fails, write the text-cleaned version as-is
            with open(dst_path, "w", encoding="utf-8") as dst:
                dst.write(cleaned)


def refresh_cache() -> None:
    """Clear .conf and rebuild from source inventories."""
    if os.path.isdir(CONF_DIR):
        shutil.rmtree(CONF_DIR)
    build_cache()


def get_cached_path(server_type: str) -> str:
    return _cached_name(server_type)
