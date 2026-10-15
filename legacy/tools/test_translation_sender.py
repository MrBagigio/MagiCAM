"""
Test sender that sends two matrices: one with translation in row-major slots (indices 3,7,11)
and one with translation in column-major slots (indices 12,13,14). Sends each once with a pause
so you can observe Maya behavior.
Usage: python tools/test_translation_sender.py --host 127.0.0.1 --port 9000
"""
import socket
import json
import time
import argparse

def main(args):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Identity matrix row-major
    identity = [1.0,0.0,0.0,0.0,
                0.0,1.0,0.0,0.0,
                0.0,0.0,1.0,0.0,
                0.0,0.0,0.0,1.0]

    # Row-major translation (tx,ty,tz at indices 3,7,11)
    row_trans = list(identity)
    row_trans[3] = 1.0
    row_trans[7] = 2.0
    row_trans[11] = 3.0

    # Column-major translation (tx,ty,tz at indices 12,13,14)
    col_trans = list(identity)
    col_trans[12] = 1.0
    col_trans[13] = 2.0
    col_trans[14] = 3.0

    print(f"Sending row-major translation to {args.host}:{args.port}: tx=1 ty=2 tz=3 (indices 3,7,11)")
    payload = {'matrix': row_trans, 't': time.time()}
    sock.sendto(json.dumps(payload).encode('utf8'), (args.host, args.port))

    time.sleep(1.0)

    print(f"Sending column-major translation to {args.host}:{args.port}: tx=1 ty=2 tz=3 (indices 12,13,14)")
    payload = {'matrix': col_trans, 't': time.time()}
    sock.sendto(json.dumps(payload).encode('utf8'), (args.host, args.port))

    print('Done.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9000)
    args = parser.parse_args()
    main(args)
