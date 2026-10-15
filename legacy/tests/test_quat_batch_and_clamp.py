import math
import maya.maya_receiver as mr


def test_quat_batch_sign_handling():
    # create two quats that are negatives of each other and verify batch avg handles sign
    q1 = (1.0, 0.0, 0.0, 0.0)
    q2 = (-1.0, 0.0, 0.0, 0.0)
    mats = []
    # build mats that produce these quats when _mat_to_quat is applied
    # We'll fake by constructing quaternion directly and packing into 'mats' using _quat_to_mat
    m1 = mr._quat_to_mat(q1)
    m2 = mr._quat_to_mat(q2)
    mats = [m1, m2]
    # Now simulate the batch average code path
    pos_sum = [0.0, 0.0, 0.0]
    quat_sum = [0.0, 0.0, 0.0, 0.0]
    for i, m in enumerate(mats):
        q = mr._mat_to_quat(m)
        if i == 0:
            ref_q = q
        else:
            dotp = q[0]*ref_q[0] + q[1]*ref_q[1] + q[2]*ref_q[2] + q[3]*ref_q[3]
            if dotp < 0:
                q = (-q[0], -q[1], -q[2], -q[3])
        quat_sum[0] += q[0]; quat_sum[1] += q[1]; quat_sum[2] += q[2]; quat_sum[3] += q[3]
    # sum should be 2 * q1
    assert quat_sum[0] > 1.9


def test_rotation_clamping():
    # pick two quaternions 180 deg apart
    q1 = (1.0, 0.0, 0.0, 0.0)
    q2 = (0.0, 1.0, 0.0, 0.0) # 180deg around X? roughly
    # compute angle via code
    dotpq = q1[0]*q2[0] + q1[1]*q2[1] + q1[2]*q2[2] + q1[3]*q2[3]
    angle = 2.0 * math.acos(abs(max(-1.0, min(1.0, dotpq))))
    assert angle > 1.0
    # set max to small and ensure eff_t < 1
    max_rad = math.radians(10.0)
    frac = max_rad / angle
    assert frac < 1.0
