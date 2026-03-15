"""
Manages the .conf cache folder.
Copies inventory YAML files from CSV paths, strips comments, never touches originals.
"""
import os
import shutil
import csv
from constants import CSV_FILE, CONF_DIR


def _uncomment_lines(text: str) -> str:
    """Uncomment lines that start with # — preserve indentation, keep content."""
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # Measure leading whitespace, then remove the leading '# ' or '#'
            indent = line[: len(line) - len(stripped)]
            uncommented = stripped[1:]          # drop the '#'
            if uncommented.startswith(" "):     # drop one optional space after '#'
                uncommented = uncommented[1:]
            lines.append(indent + uncommented)
        else:
            lines.append(line)
    return "\n".join(lines)


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
            with open(dst_path, "w", encoding="utf-8") as dst:
                dst.write(cleaned)


def refresh_cache() -> None:
    """Clear .conf and rebuild from source inventories."""
    if os.path.isdir(CONF_DIR):
        shutil.rmtree(CONF_DIR)
    build_cache()


def get_cached_path(server_type: str) -> str:
    return _cached_name(server_type)
