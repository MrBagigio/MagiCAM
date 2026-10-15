import math
import pytest

import importlib

# Import functions from maya_receiver
import maya.maya_receiver as maya_receiver


def test_quat_mat_roundtrip():
    # Identity matrix -> quaternion -> matrix should roundtrip
    idm = [1.0,0.0,0.0,0.0,
           0.0,1.0,0.0,0.0,
           0.0,0.0,1.0,0.0,
           0.0,0.0,0.0,1.0]
    q = maya_receiver._mat_to_quat(idm)
    mat = maya_receiver._quat_to_mat(q)
    # compare rotation portion (3x3)
    for i in range(3):
        for j in range(3):
            assert abs(mat[i*4 + j] - idm[i*4 + j]) < 1e-6


def test_slerp_identity():
    a = (1.0, 0.0, 0.0, 0.0)
    b = (1.0, 0.0, 0.0, 0.0)
    res = maya_receiver._quat_slerp(a, b, 0.5)
    assert all(abs(res[i] - a[i]) < 1e-6 for i in range(4))
