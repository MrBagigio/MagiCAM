"""
Stress test sender for the MagiCAM receiver.
Usage: python tools/test_stress_sender.py --host 192.168.1.107 --port 9000 --rate 200 --duration 10 --burst 0
Options:
 - rate: average packets per second
 - burst: if >0, send bursts of `burst` packets at once
 - corrupt: fraction of packets to corrupt
"""
import socket
import json
import time
import argparse
import random

def main(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def make_matrix(t):
        import math
        c = math.cos(t)
        s = math.sin(t)
        return [c,-s,0,1.0, s,c,0,2.0, 0,0,1,3.0, 0,0,0,1]

    end = time.time() + args.duration
    interval = 1.0 / max(1, args.rate)
    while time.time() < end:
        t = time.time()
        if args.burst > 0 and random.random() < 0.1:
            # send burst
            for i in range(args.burst):
                mat = make_matrix(t + i*0.01)
                payload = {'type':'pose','matrix':mat,'t':t}
                b = json.dumps(payload).encode('utf8')
                if random.random() < args.corrupt:
                    b = b[:len(b)//2]  # corrupt
                sock.sendto(b, (args.host, args.port))
        else:
            mat = make_matrix(t)
            payload = {'type':'pose','matrix':mat,'t':t}
            b = json.dumps(payload).encode('utf8')
            if random.random() < args.corrupt:
                b = b[:len(b)//2]
            sock.sendto(b, (args.host, args.port))
        time.sleep(interval)

    print('Stress sender finished')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9000)
    parser.add_argument('--rate', type=int, default=100)
    parser.add_argument('--duration', type=int, default=10)
    parser.add_argument('--burst', type=int, default=0)
    parser.add_argument('--corrupt', type=float, default=0.0)
    args = parser.parse_args()
    main(args)