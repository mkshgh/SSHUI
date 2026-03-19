"""
Loads and saves user config from config.json.
Stores default port forwards and theme preference.
"""
import json
import os
from typing import List, Dict, Any

CONFIG_FILE = "config.json"

_DEFAULTS: Dict[str, Any] = {
    "default_forwards": [],
    "theme": "textual-dark",
}


def load_config() -> Dict[str, Any]:
    if not os.path.isfile(CONFIG_FILE):
        return dict(_DEFAULTS)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # fill missing keys with defaults
        for k, v in _DEFAULTS.items():
            data.setdefault(k, v)
        return data
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULTS)


def save_config(config: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
