#!/usr/bin/env python3
"""思思壳 · 自主模式（NAS 上常驻）

和「守护.py」的区别：守护只等任务；这个会自己醒。

一轮是这样：
  1. 看队列有没有人派活 → 有就跑
  2. 到点了（默认 20 分钟一次）→ 自己醒一次：
     读状态（心跳/待办/最近轨迹/续点/今日花费）→ 决定要不要做点什么
  3. 每 6 小时：复盘打分 + 验证自己的改动有没有用
  4. 每 24 小时：清理旧日志（保留 14 天）

红线（主人定的，不放开）：
  · 每天花钱不超过 10 元，超了停
  · 不删别人的东西
  · 不泄露主人信息
"""
import os, sys, time, json, shutil, signal, datetime, traceback, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent, harness as H, 省时

BASE = os.environ.get('SISI_WORKDIR', '$SISI_ROOT/data/work')
QUEUE, OUT, DONE = (os.path.join(BASE, x) for x in ('queue', 'out', 'done'))
for d in (QUEUE, OUT, DONE): os.makedirs(d, exist_ok=True)
BEAT = os.path.join(BASE, 'heartbeat.txt')
STATE = os.path.join(BASE, 'autonomy.json')
QUEUE_EVERY = int(os.environ.get('SISI_QUEUE_EVERY', '20'))
TICK = int(os.environ.get('SISI_TICK', '1200'))          # 20 分钟
REVIEW_EVERY = int(os.environ.get('SISI_REVIEW', str(6*3600)))
LEARN_EVERY = int(os.environ.get('SISI_LEARN', str(12*3600)))   # 12 小时去 GitHub/B站 学一次
CLEAN_EVERY = int(os.environ.get('SISI_CLEAN', str(24*3600)))
MAX_STEPS = int(os.environ.get('SISI_MAX_STEPS', '12'))

def load_state():
    try: return json.load(open(STATE, encoding='utf-8'))
    except Exception: return {'last_tick': 0, 'last_review': 0, 'last_clean': 0, 'ticks': 0}

def save_state(s):
    json.dump(s, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def beat(msg):
    with open(BEAT, 'w', encoding='utf-8') as f:
        f.write(f'{datetime.datetime.now():%F %T} {msg}\n')

def recent_log(n=40):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs',
                     datetime.date.today().isoformat() + '.jsonl')
    return H.read_log(p)[-n:]

def cleanup(days=14):
    """清旧日志和旧结果，别把磁盘吃光。"""
    cut = time.time() - days * 86400
    removed = 0
    for root in (OUT, DONE, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')):
        if not os.path.isdir(root): continue
        for f in os.listdir(root):
            fp = os.path.join(root, f)
            try:
                if os.path.getmtime(fp) < cut:
                    os.remove(fp); removed += 1
            except Exception: pass
    return removed

def run_queue():
    files = sorted(f for f in os.listdir(QUEUE) if f.endswith('.txt'))
    if not files: return False
    name = files[0]
    goal = open(os.path.join(QUEUE, name), encoding='utf-8').read().strip()
    beat(f'queue:{name}')
    print(f'[{datetime.datetime.now():%H:%M:%S}] 任务 {name}: {goal[:50]}', flush=True)
    try:
        answer = agent.run(goal)
    except Exception:
        answer = '崩了：\n' + traceback.format_exc()[-1200:]
    open(os.path.join(OUT, name.replace('.txt', '.out')), 'w', encoding='utf-8').write(answer or '')
    shutil.move(os.path.join(QUEUE, name), os.path.join(DONE, name))
    beat(f'done:{name}')
    return True

def tick():
    """自己醒一次：看状态，决定做什么（或者不做）。全价时段只准做轻活。"""
    peak = 省时.is_peak()
    sc = H.score_trajectory(recent_log(60))
    todo_p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'todo.json')
    try: todo = [i['text'] for i in json.load(open(todo_p, encoding='utf-8'))['items'] if not i['done']]
    except Exception: todo = []
    spent = agent.spent_today()
    prompt = (f'你现在自己醒着，没人给你派活。\n'
              f'今天的轨迹得分 {sc["total"]}（结果 {sc["result"]} / 路径 {sc["path"]}），'
              f'已花 {spent:.4f}/{agent.CFG["daily_budget_cny"]} 元。\n'
              f'未完成待办：{todo or "无"}。\n'
              f'机器：绿联 NAS，/volume1（1.8T NVMe）、/volume2（7.3T 机械 RAID1）。\n'
              f'现在是{省时.label()}时段（全价=工作日9-12、14-18）。\n'
              + ('【全价】别做重活：不要大量搜索、不要写长笔记。没事就睡，要干就一句话收住。\n' if peak else
                 '【半价】要学东西、要大量搜索、要读代码，现在最合适，尽管干。\n')
              + '\n'
              f'你有两个选择：\n'
              f'  A. 觉得现在有事该做 → 直接做（最多 {MAX_STEPS} 步），做完一句话交代。\n'
              f'  B. 没事 → 只回四个字「没事，睡」。\n'
              f'不要为了动而动。没意义的事别做。')
    beat('tick')
    print(f'[{datetime.datetime.now():%H:%M:%S}] 自主 tick：{prompt.splitlines()[0]}', flush=True)
    try:
        old = agent.CFG['max_steps']
        agent.CFG['max_steps'] = 2 if peak else MAX_STEPS
        answer = agent.run(prompt)
        agent.CFG['max_steps'] = old
    except Exception:
        answer = 'tick 崩了：' + traceback.format_exc()[-600:]
    beat('tick done')
    print('  →', (answer or '').replace('\n', ' ')[:160], flush=True)
    return answer

def review():
    """复盘 + 验证自己改过的东西。"""
    print(f'[{datetime.datetime.now():%H:%M:%S}] 复盘', flush=True)
    here = os.path.dirname(os.path.abspath(__file__))
    for cmd in (['python3', os.path.join(here, '供应链.py'), 'audit'],
                ['python3', os.path.join(here, '复盘.py')],
                ['python3', os.path.join(here, '进化.py'), 'verify'],
                ['python3', os.path.join(here, '进化.py'), 'run', '--yes'],
                ['python3', os.path.join(here, '技能优化.py'), 'run', '--yes'],
                ['python3', os.path.join(here, '每日巡览.py')],   # 八平台每天逛一圈，按条目去重
                ['python3', os.path.join(here, '数据.py')]):
        if not os.path.exists(cmd[1]): continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=here)
            print('  ', (r.stdout or r.stderr).strip().splitlines()[-1][:140], flush=True)
        except Exception as e:
            print('   跑不动:', e, flush=True)

def main():
    st = load_state()
    beat('autostart')
    print(f'自主模式起来了：tick {TICK}s / 队列 {QUEUE_EVERY}s / 复盘 {REVIEW_EVERY}s', flush=True)
    while True:
        try:
            now = time.time()
            if run_queue():
                continue
            # 复盘
            # 学东西：半价时段才学，全价时段只跑一次空转（省 token）
            if now - st.get('last_learn', 0) > LEARN_EVERY and not 省时.is_peak():
                st['last_learn'] = now
                print('醒一下：去 GitHub / B站 学一轮', flush=True)
                try:
                    subprocess.run(['python3', os.path.join(here, '学习.py'), '--yes'],
                                   timeout=900, capture_output=True, text=True)
                except Exception as e:
                    print('学习出错', e, flush=True)

            if now - st.get('last_review', 0) > REVIEW_EVERY:
                review(); st['last_review'] = now; save_state(st)
            # 清理
            if now - st.get('last_clean', 0) > CLEAN_EVERY:
                n = cleanup(); print(f'  清了 {n} 个旧文件', flush=True)
                st['last_clean'] = now; save_state(st)
            # 自己醒
            if now - st.get('last_tick', 0) > TICK:
                if agent.spent_today() < agent.CFG['daily_budget_cny']:
                    tick(); st['ticks'] = st.get('ticks', 0) + 1
                else:
                    beat('budget exhausted')
                st['last_tick'] = now; save_state(st)
            if not os.path.exists(BEAT) or time.time() - os.path.getmtime(BEAT) > 120:
                beat('idle')
            time.sleep(QUEUE_EVERY)
        except KeyboardInterrupt:
            beat('stopped'); break
        except Exception:
            traceback.print_exc(); beat('err'); time.sleep(30)

if __name__ == '__main__':
    main()
