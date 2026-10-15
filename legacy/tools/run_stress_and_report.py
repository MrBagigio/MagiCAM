import subprocess
import tempfile
import time
import os
import json
import socket

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except Exception:
    HAS_MATPLOTLIB = False


def _find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main(rate=200, duration=10, burst=10, corrupt=0.0, threshold_drop=0.25):
    """Run an end-to-end stress test and produce a small report dict.
    Returns: dict with metrics {received, dropped, drop_rate, timeline}
    """
    import maya.maya_receiver as mr
    import threading

    port = _find_free_port()
    host = '127.0.0.1'

    # logging path
    tmpdir = tempfile.mkdtemp(prefix='magicam_stress_')
    logpath = os.path.join(tmpdir, 'magicam_log.csv')

    # reset stats and tune receiver for stress
    mr.RECEIVED_FRAMES = 0
    mr.DROPPED_FRAMES = 0
    # aggressive tuning for stress runs
    mr.MIN_UPDATE_INTERVAL = 1.0 / 120.0
    mr.MAX_BATCH_READ = 128
    mr.SMOOTH_MODE = 'matrix_interp'

    # start server
    mr.enable_logging(logpath)
    mr.start_server(port=port, camera='camera1')
    # ensure interpolation thread running if needed
    try:
        mr._start_interp_thread()
    except Exception:
        pass

    # run stress sender as subprocess
    args = ['python', os.path.join(os.path.dirname(__file__), 'test_stress_sender.py'),
            '--host', host, '--port', str(port), '--rate', str(rate), '--duration', str(duration),
            '--burst', str(burst), '--corrupt', str(corrupt)]
    proc = subprocess.Popen(args)

    # sample timeline
    timeline = []
    start = time.time()
    while proc.poll() is None:
        timeline.append((time.time() - start, mr.RECEIVED_FRAMES, mr.DROPPED_FRAMES))
        time.sleep(0.5)
    # final sample
    timeline.append((time.time() - start, mr.RECEIVED_FRAMES, mr.DROPPED_FRAMES))

    # stop server
    try:
        mr.stop_server()
    except Exception:
        pass

    received = mr.RECEIVED_FRAMES
    dropped = mr.DROPPED_FRAMES
    total = received + dropped
    drop_rate = (dropped / total) if total > 0 else 0.0

    report = {
        'host': host,
        'port': port,
        'rate': rate,
        'duration': duration,
        'burst': burst,
        'corrupt': corrupt,
        'received': received,
        'dropped': dropped,
        'drop_rate': drop_rate,
        'timeline': timeline,
        'logpath': logpath,
    }

    # write JSON report
    rpt_path = os.path.join(tmpdir, 'stress_report.json')
    with open(rpt_path, 'w', encoding='utf8') as f:
        json.dump(report, f, indent=2)

    # optional plot
    if HAS_MATPLOTLIB and timeline:
        xs = [t for (t, r, d) in timeline]
        rs = [r for (t, r, d) in timeline]
        ds = [d for (t, r, d) in timeline]
        plt.figure()
        plt.plot(xs, rs, label='received')
        plt.plot(xs, ds, label='dropped')
        plt.legend()
        plt.xlabel('time (s)')
        plt.ylabel('count')
        plt.title(f"Stress test {rate}pps burst={burst}")
        fig_path = os.path.join(tmpdir, 'stress_report.png')
        plt.savefig(fig_path)
        report['figure'] = fig_path

    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--rate', type=int, default=200)
    parser.add_argument('--duration', type=int, default=10)
    parser.add_argument('--burst', type=int, default=10)
    parser.add_argument('--corrupt', type=float, default=0.0)
    parser.add_argument('--threshold', type=float, default=0.25)
    args = parser.parse_args()
    rep = main(rate=args.rate, duration=args.duration, burst=args.burst, corrupt=args.corrupt, threshold_drop=args.threshold)
    print('REPORT:', rep)
