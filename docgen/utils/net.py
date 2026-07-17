import socket
from functools import lru_cache


@lru_cache(maxsize=1)
def shields_reachable(timeout: float = 1.5) -> bool:
    """Best-effort check that shields.io is reachable (for badge images).

    Returns False offline / on network error so callers can fall back to
    offline-safe text badges instead of broken images.
    """
    try:
        with socket.create_connection(("shields.io", 443), timeout=timeout):
            return True
    except OSError:
        return False
