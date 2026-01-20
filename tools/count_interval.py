cnt=0
start=1768929241.0
end=1768929251.0
with open('C:/temp/magicam_log.csv','r',encoding='utf8') as f:
    for line in f:
        try:
            parts=line.split(',')
            t=float(parts[0])
            if start <= t <= end and ',pose,' in line:
                cnt+=1
        except Exception:
            pass
print('pose_count_interval=',cnt)
