#!/usr/bin/env python3
"""NAS 上的常驻守护：看队列文件，来了任务就跑一次 agent。

队列：data/queue/*.txt （放一个任务，一行目标）
结果：data/out/<同名>.out
跑完的任务挪到 data/done/
"""
import os, sys, time, shutil, datetime, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent

BASE = os.environ.get('SISI_WORKDIR', '$SISI_ROOT/data/work')
QUEUE = os.path.join(BASE, 'queue'); OUT = os.path.join(BASE, 'out'); DONE = os.path.join(BASE, 'done')
for d in (QUEUE, OUT, DONE): os.makedirs(d, exist_ok=True)
HEARTBEAT = os.path.join(BASE, 'heartbeat.txt')

def beat(msg):
    with open(HEARTBEAT, 'w', encoding='utf-8') as f:
        f.write(f'{datetime.datetime.now():%F %T} {msg}\n')

beat('start')
print('守护起来了，看着', QUEUE, flush=True)
while True:
    try:
        files = sorted(f for f in os.listdir(QUEUE) if f.endswith('.txt'))
        if not files:
            beat('idle'); time.sleep(10); continue
        name = files[0]
        goal = open(os.path.join(QUEUE, name), encoding='utf-8').read().strip()
        beat(f'got {name}')
        print(f'[{datetime.datetime.now():%H:%M:%S}] 跑任务 {name}: {goal[:60]}', flush=True)
        try:
            answer = agent.run(goal)
        except Exception:
            answer = '崩了：\n' + traceback.format_exc()[-1500:]
        open(os.path.join(OUT, name.replace('.txt', '.out')), 'w', encoding='utf-8').write(answer or '')
        shutil.move(os.path.join(QUEUE, name), os.path.join(DONE, name))
        beat(f'done {name}')
        print('完成，结果在 out/' + name.replace('.txt', '.out'), flush=True)
    except Exception:
        beat('err')
        traceback.print_exc()
        time.sleep(15)
