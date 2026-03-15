"""
Fast in-memory search/filter logic for hosts and server groups.
"""
from typing import List
from inventory.loader import Host


def filter_hosts(hosts: List[Host], query: str) -> List[Host]:
    """Filter hosts by query matching name, ip, user, or port."""
    if not query:
        return hosts
    q = query.lower()
    return [
        h for h in hosts
        if q in h.name.lower()
        or q in h.ip.lower()
        or q in h.user.lower()
        or q in str(h.port)
    ]


def filter_groups(groups: List[str], query: str) -> List[str]:
    """Filter server group names by query."""
    if not query:
        return groups
    q = query.lower()
    return [g for g in groups if q in g.lower()]
