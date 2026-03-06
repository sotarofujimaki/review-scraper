"""Tor utility functions shared by scraper modules."""
import socket
import subprocess
import time

from config import TOR_SOCKS_HOST, TOR_SOCKS_PORT, TOR_PROXY_URL, TOR_CIRCUIT_WAIT


def is_tor_available() -> bool:
    """Return True if Tor SOCKS port is reachable."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        result = s.connect_ex((TOR_SOCKS_HOST, TOR_SOCKS_PORT))
        s.close()
        return result == 0
    except Exception:
        return False


def renew_circuit() -> bool:
    """Request a new Tor circuit (new exit IP) and verify Tor is running."""
    try:
        subprocess.run(["pkill", "-HUP", "tor"], timeout=5, capture_output=True)
        time.sleep(TOR_CIRCUIT_WAIT)
        return is_tor_available()
    except Exception:
        return False


def get_proxy_for_retry(retry: int) -> str | None:
    """Return proxy URL for this retry attempt. Tor first (GCP IP is known)."""
    if retry <= 2:
        # 最初の3回はTor（GCP IPより先にTor）
        if retry > 0:
            renew_circuit()  # 2回目以降は回線更新
        if is_tor_available():
            return TOR_PROXY_URL
        return None
    # 残りは直接
    return None
