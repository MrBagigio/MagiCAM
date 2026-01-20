"""
Simple UDP test sender to simulate ARKit matrix messages.
Usage: python test_sender.py --host 192.168.1.100 --port 9000
"""
import socket
import json
import time
import math

HOST = '127.0.0.1'
PORT = 9000

import argparse
def main(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def make_rot_z(theta):
        c = math.cos(theta)
        s = math.sin(theta)
        return [c,-s,0,0, s,c,0,0, 0,0,1,0, 0,0,0,1]

    t=0.0
    while True:
        rot = make_rot_z(t)
        payload = {'matrix': rot, 't': time.time()}
        data = json.dumps(payload).encode('utf8')
        sock.sendto(data, (args.host, args.port))
        t += 0.05
        time.sleep(0.05)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=HOST)
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args()
    main(args)
