"""Bonjour/mDNS: il PC pubblica `_magicam._udp.local.` cosi' il telefono lo trova senza scrivere l'IP.

Usa `zeroconf` se installato (`pip install magicam[discovery]`); senza, `Advertiser.available` e' False e il
resto di MagiCAM funziona con l'IP a mano. Il token di pairing NON va nel TXT: si legge sul pannello.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from magicam import PROTOCOL_VERSION, __version__

log = logging.getLogger("magicam.discovery")

SERVICE_TYPE = "_magicam._udp.local."

try:
    import zeroconf as _zc

    _HAS_ZEROCONF = True
except ImportError:  # pragma: no cover - dipende dall'ambiente
    _zc = None  # type: ignore[assignment]
    _HAS_ZEROCONF = False


def local_ipv4_addresses() -> list[str]:
    """Gli IPv4 non di loopback della macchina (l'ordine mette prima quello della rotta di default)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # nessun pacchetto parte: serve solo a scegliere l'interfaccia
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


class Advertiser:
    def __init__(self, port: int, name: str | None = None, addresses: list[str] | None = None) -> None:
        self.port = port
        self.name = name or f"MagiCAM {socket.gethostname()}"
        self.addresses = addresses
        self._zc: Any = None
        self._info: Any = None

    @property
    def available(self) -> bool:
        return _HAS_ZEROCONF

    @property
    def running(self) -> bool:
        return self._zc is not None

    def start(self) -> bool:
        if not _HAS_ZEROCONF:
            log.warning("zeroconf non installato: nessun annuncio Bonjour, scrivi l'IP sul telefono")
            return False
        if self.running:
            return True
        addrs = self.addresses or local_ipv4_addresses()
        if not addrs:
            log.warning("nessun IPv4 locale: nessun annuncio Bonjour")
            return False
        self._info = _zc.ServiceInfo(
            SERVICE_TYPE,
            f"{self.name}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(a) for a in addrs],
            port=self.port,
            properties={"magicam": __version__, "protocol": str(PROTOCOL_VERSION)},
            server=f"{socket.gethostname()}.local.",
        )
        self._zc = _zc.Zeroconf()
        self._zc.register_service(self._info)
        log.info("annuncio Bonjour «%s» su %s:%d", self.name, ",".join(addrs), self.port)
        return True

    def stop(self) -> None:
        if self._zc is None:
            return
        try:
            self._zc.unregister_service(self._info)
        finally:
            self._zc.close()
            self._zc = None
            self._info = None
