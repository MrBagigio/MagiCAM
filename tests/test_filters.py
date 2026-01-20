import time
import maya.maya_receiver as maya_receiver


def test_alphabeta_filter_basic():
    f = maya_receiver.AlphaBetaFilter(alpha=0.5, beta=0.01)
    f.reset(0.0)
    v = f.update(1.0, t=1.0)
    # First update returns the measurement (no prior timestamp)
    assert abs(v - 1.0) < 1e-6
    v2 = f.update(2.0, t=2.0)
    assert v2 != v
