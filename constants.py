from typing import List

CSV_FILE: str = "servers.csv"
LOG_FILE: str = "ssh_login.log"
CONF_DIR: str = ".conf"

DEFAULT_PORTS: List[dict] = [
    {"label": "Postgres  5432", "local": 5432, "remote": 5432},
    {"label": "HTTP      80",   "local": 80,   "remote": 80},
    {"label": "HTTPS     443",  "local": 443,  "remote": 443},
    {"label": "8080",           "local": 8080, "remote": 8080},
    {"label": "3000",           "local": 3000, "remote": 3000},
    {"label": "Redis     6379", "local": 6379, "remote": 6379},
]
