# -*- coding: utf-8 -*-
"""Shared HTTP helpers: local proxy probe for OpenRouter."""
from __future__ import annotations


def detect_proxies() -> dict[str, str] | None:
    """Prefer agent sidecar 17890, then v2rayN 10808/10809. None = direct."""
    import socket

    def probe(port: int) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            return False

    if probe(17890):
        url = "http://127.0.0.1:17890"
        return {"http": url, "https": url}
    if probe(10809):
        url = "http://127.0.0.1:10809"
        return {"http": url, "https": url}
    if probe(10808):
        url = "socks5h://127.0.0.1:10808"
        return {"http": url, "https": url}
    return None
