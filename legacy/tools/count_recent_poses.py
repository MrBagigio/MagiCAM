import time
path = r'C:/temp/magicam_log.csv'
now = time.time()
count = 0
try:
    with open(path,'r',encoding='utf8') as f:
        for line in f:
            try:
                parts = line.split(',')
                t = float(parts[1])
                if t >= now - 20 and 'pose' in line:
                    count += 1
            except Exception:
                pass
    print('pose_count_last_20s=', count)
except FileNotFoundError:
    print('log not found')
