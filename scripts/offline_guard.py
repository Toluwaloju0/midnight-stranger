#!/usr/bin/env python3
"""Phase 4: run the radio while refusing every network connection that leaves this computer.

    python scripts/offline_guard.py                 # real models (Ollama is on localhost, so it is allowed)
    python scripts/offline_guard.py --fake --port 8140

Any attempt to reach a non-local address is blocked and logged. When you stop the
server (Ctrl+C) it prints the list; an empty list is the proof for the post. This does
not replace the airplane-mode test (turn Wi-Fi off and restart), it backs it up.
"""
from __future__ import annotations

import ipaddress
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

blocked: list[str] = []
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _is_local(host) -> bool:
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback or ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def _check(address) -> None:
    if isinstance(address, tuple) and address and not _is_local(address[0]):
        blocked.append(f"connect {address[0]}:{address[1] if len(address) > 1 else ''}")
        raise OSError(f"offline_guard: blocked connection to {address[0]}")


def guarded_connect(self, address):
    if self.family != socket.AF_UNIX:
        _check(address)
    return _real_connect(self, address)


def guarded_connect_ex(self, address):
    if self.family != socket.AF_UNIX:
        _check(address)
    return _real_connect_ex(self, address)


def guarded_getaddrinfo(host, *a, **k):
    if not _is_local(host):
        blocked.append(f"dns {host}")
        raise socket.gaierror(f"offline_guard: blocked lookup of {host}")
    return _real_getaddrinfo(host, *a, **k)


socket.socket.connect = guarded_connect
socket.socket.connect_ex = guarded_connect_ex
socket.getaddrinfo = guarded_getaddrinfo

from app import cli  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    print("offline_guard: only connections to this computer are allowed.", flush=True)
    try:
        code = cli.main(["serve", *args])
    except KeyboardInterrupt:
        code = 0
    print("\n=== offline_guard report ===")
    if blocked:
        print(f"{len(blocked)} blocked attempt(s):")
        for item in sorted(set(blocked)):
            print("  ", item)
    else:
        print("No attempts to leave this computer. 0 blocked.")
    raise SystemExit(code)