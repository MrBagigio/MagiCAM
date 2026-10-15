"""F4.5 fuori da Maya: 60 Hz per qualche secondo, loopback: niente perso, memoria che non cresce a dismisura.

La corsa da 10 minuti e' `python -m magicam.stress --duration 600`; la parte DENTRO Maya (CPU e memoria del
processo Maya) resta da fare col si' dell'utente.
"""

from magicam.stress import run


def test_stress_short_run_loses_nothing_and_memory_stays_bounded():
    r = run(duration_s=4.0, rate_hz=60.0, record=True, realtime=True)
    assert r.received + r.reordered + r.lost == r.sent or r.received >= r.sent - 2  # ultimo pacchetto in volo
    assert r.lost == 0 and r.reordered == 0
    assert r.updates >= r.sent * 0.9
    assert r.samples_recorded == r.updates
    assert r.mean_update_us < 500.0, r.mean_update_us
    # 4 s di take = ~240 campioni da ~300 byte: la crescita e' quasi tutta la take; sotto 2 MiB per costruzione
    assert r.mem_growth_kib < 2048, r.mem_growth_kib
