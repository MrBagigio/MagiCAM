"""
OSC binary test sender: sends /pose_bin or /calib_bin with 16 float32 in big-endian as blob.
Requires python-osc: pip install python-osc
Usage: python osc_binary_sender.py --host 192.168.1.100 --port 9000 --type pose_bin
"""
import struct
import time
import argparse

try:
    from pythonosc import udp_client
    from pythonosc import osc_message_builder
except Exception as e:
    print('python-osc not installed. Install with: python -m pip install python-osc')
    raise

parser = argparse.ArgumentParser()
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=9000)
parser.add_argument('--type', choices=['pose_bin','calib_bin'], default='pose_bin')
args = parser.parse_args()

client = udp_client.SimpleUDPClient(args.host, args.port)

def make_rot_z(theta):
    import math
    c = math.cos(theta)
    s = math.sin(theta)
    return [c,-s,0,0, s,c,0,0, 0,0,1,0, 0,0,0,1]

if __name__ == '__main__':
    t=0.0
    while True:
        mat = make_rot_z(t)
        payload = struct.pack('!16f', *mat)
        builder = osc_message_builder.OscMessageBuilder(address='/' + args.type)
        builder.add_arg(payload, arg_type='b')
        msg = builder.build()
        client.send(msg)
        t += 0.05
        time.sleep(0.05)
