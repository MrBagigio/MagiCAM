"""F4.2: l'annuncio Bonjour si vede da un browser mDNS sulla stessa macchina (zeroconf richiesto)."""

import socket
import threading
import uuid

import pytest

from magicam import discovery
from magicam.discovery import SERVICE_TYPE, Advertiser, local_ipv4_addresses

zeroconf = pytest.importorskip("zeroconf")


def test_local_ipv4_addresses_are_well_formed():
    for ip in local_ipv4_addresses():
        socket.inet_aton(ip)
        assert not ip.startswith("127.")


def test_advertiser_is_found_by_a_browser():
    name = f"magicam-test-{uuid.uuid4().hex[:8]}"
    adv = Advertiser(port=19001, name=name)
    assert adv.available
    if not local_ipv4_addresses():
        pytest.skip("nessun IPv4 locale")
    found = threading.Event()
    seen: dict[str, int] = {}

    class Listener:
        def add_service(self, zc, type_, sname):
            if sname.startswith(name):
                info = zc.get_service_info(type_, sname, timeout=2000)
                if info is not None:
                    seen["port"] = info.port
                    seen["protocol"] = int(info.properties[b"protocol"])
                    found.set()

        def remove_service(self, zc, type_, sname):
            pass

        def update_service(self, zc, type_, sname):
            pass

    browser_zc = zeroconf.Zeroconf()
    try:
        assert adv.start()
        assert adv.running
        zeroconf.ServiceBrowser(browser_zc, SERVICE_TYPE, Listener())
        assert found.wait(8.0), "annuncio non visto in 8 s"
        assert seen["port"] == 19001
        assert seen["protocol"] == discovery.PROTOCOL_VERSION
    finally:
        adv.stop()
        browser_zc.close()
    assert not adv.running


def test_stop_without_start_is_harmless():
    Advertiser(port=1).stop()
