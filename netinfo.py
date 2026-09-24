"""
netinfo.py - work out what address a phone should be pointed at.

The Android app asks for the server's address on first run, and the two ways
of getting that wrong are the two things everybody does: typing 127.0.0.1,
which on the phone means the phone, and leaving the server bound to localhost,
where nothing outside the laptop can reach it however right the address is.

Both are invisible from the phone: the app just says it cannot connect. So the
server works the address out and prints it, rather than leaving somebody to
find it with ipconfig and guess which of the four entries is the real one.

Standard library only, and it never sends a packet.
"""
from __future__ import annotations

import socket

# Addresses that are never worth offering to a phone.
LOOPBACK_PREFIXES = ("127.", "0.")
# 169.254.x.x is what a machine gives itself when DHCP failed; it cannot route.
LINK_LOCAL_PREFIX = "169.254."


def _primary_address() -> str | None:
    """The address this machine would use to reach the outside world.

    Opening a UDP socket towards a public address and asking what local address
    the kernel picked. UDP is connectionless, so nothing is transmitted and the
    host does not have to exist or be reachable -- this works with no network
    at all, which is the point.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.2)
        sock.connect(("10.254.254.254", 1))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _hostname_addresses() -> list[str]:
    try:
        _name, _aliases, addresses = socket.gethostbyname_ex(socket.gethostname())
        return list(addresses)
    except OSError:
        return []


def usable(address: str) -> bool:
    """Could a phone on the same network actually reach this address?"""
    if not address or ":" in address:                 # IPv6 is not worth typing
        return False
    if address.startswith(LOOPBACK_PREFIXES):
        return False
    return not address.startswith(LINK_LOCAL_PREFIX)


def lan_addresses() -> list[str]:
    """Every address a phone might reach this machine on, best guess first."""
    found: list[str] = []
    primary = _primary_address()
    if primary and usable(primary):
        found.append(primary)
    for address in _hostname_addresses():
        if usable(address) and address not in found:
            found.append(address)
    return found


def phone_urls(port: int) -> list[str]:
    return [f"http://{address}:{port}" for address in lan_addresses()]


def startup_banner(host: str, port: int) -> str:
    """What to print when the server starts, aimed at somebody holding a phone."""
    lines = ["", "  Attendance server", "  " + "-" * 52]
    lines.append(f"  On this computer:  http://127.0.0.1:{port}")

    reachable = host in ("0.0.0.0", "::", "")
    urls = phone_urls(port)

    if not reachable:
        lines += [
            "",
            "  Phones CANNOT reach this server: it is bound to this computer",
            "  only. To use the Android app, stop it and start it again with:",
            "",
            "      HOST=0.0.0.0 ./run.sh          (Windows: set HOST=0.0.0.0)",
            "",
        ]
    elif urls:
        lines += ["", "  In the phone app, type this address:", ""]
        lines += [f"      {url}" for url in urls]
        if len(urls) > 1:
            lines.append("")
            lines.append("  (Several networks found. Try the one whose first two")
            lines.append("   numbers match your phone's Wi-Fi address.)")
        lines += [
            "",
            "  The phone must be on the same Wi-Fi. If it still cannot connect,",
            "  the computer's firewall is blocking Python - allow it on private",
            "  networks.",
            "",
        ]
    else:
        lines += [
            "",
            "  Listening on all networks, but no usable address was found.",
            "  This computer may not be on a Wi-Fi or LAN right now.",
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(startup_banner("0.0.0.0", port))
