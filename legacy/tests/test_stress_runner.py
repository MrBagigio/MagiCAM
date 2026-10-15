import pytest

from tools import run_stress_and_report

@pytest.mark.stress
def test_stress_basic():
    # run a short stress test; accept up to 60% drop initially (we aim to lower this via tuning)
    rep = run_stress_and_report.main(rate=250, duration=6, burst=20, corrupt=0.02)
    drop_rate = rep.get('drop_rate', 1.0)
    print('stress report:', rep)
    assert drop_rate < 0.60
