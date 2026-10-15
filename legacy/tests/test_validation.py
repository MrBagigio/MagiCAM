import math
import maya.maya_receiver as maya_receiver


def test_validate_matrix_good():
    m = [1.0]*16
    assert maya_receiver._validate_matrix(m)


def test_validate_matrix_nan():
    m = [1.0]*16
    m[0] = float('nan')
    assert not maya_receiver._validate_matrix(m)


def test_validate_matrix_huge_translation():
    m = [1.0]*16
    m[3] = 1e6
    assert not maya_receiver._validate_matrix(m)
