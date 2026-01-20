import json
import maya.maya_receiver as maya_receiver


def test_process_packet_applies_matrix(fake_maya_cmds):
    # ensure immediate apply
    maya_receiver.SMOOTH_MODE = 'none'
    mat = [1.0,0.0,0.0,1.0,
           0.0,1.0,0.0,2.0,
           0.0,0.0,1.0,3.0,
           0.0,0.0,0.0,1.0]
    payload = json.dumps({'type':'pose','matrix': mat}).encode('utf8')
    maya_receiver._process_packet(payload)
    # fake_maya_cmds stored last matrix
    last = fake_maya_cmds._last
    assert last[3] == 1.0 and last[7] == 2.0 and last[11] == 3.0
