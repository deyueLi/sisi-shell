#!/usr/bin/env python3
"""步数观测：max_steps=45 到底够不够，用数据说话。

背景（2026-10-29）：上限从 30 提到 45，但 45 也是拍的。
主人要求「生成日志，24 小时 / 72 小时 / 一周后各查一次」。
所以这个脚本只干三件事：
  1. 扫运行日志，统计每次跑到第几步、有没有撞上限、花了多少钱
  2. 把结果追加进 知识/步数观测.md（每次检查留一行，能看出趋势）
  3. 给出结论：够 / 不太够 / 不够（给建议值）

判定标准（先定死，免得事后找借口）：
  · 撞上限的比例 > 10%   → 上限太低，建议抬
  · 撞上限的比例在 3~10% → 观察
  · 撞上限的比例 < 3%    → 够用
  · 平均步数低不算问题（主人 2026-10-29 定）：留富余是为了让复杂任务撞不到线，不为了省钱去降

用法：
  python3 步数观测.py            看最近 7 天
  python3 步数观测.py --days 1   只看最近 24 小时
"""
import os, sys, json, glob, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get('SISI_WORKDIR', os.path.dirname(HERE))
LOG_DIRS = [os.path.join(HERE, 'logs'), os.path.join(W, '日志')]
OUT = os.path.join(W, '知识', '步数观测.md')
LIMIT = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8')).get('max_steps', 45)


def read_runs(days=7):
    """把日志切成「一次运行」。判据：出现 goal 或 step 回到 1 就算新的一次。"""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    runs, cur, last_step = [], None, None
    for d in LOG_DIRS:
        for f in sorted(glob.glob(os.path.join(d, '20*.jsonl'))):
            try:
                lines = open(f, encoding='utf-8').read().splitlines()
            except Exception:
                continue
            for ln in lines:
                if not ln.strip():
                    continue
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                st = r.get('step')
                if (r.get('goal') is not None or (st == 1 and last_step not in (None, 0) and last_step > 1)) and cur:
                    runs.append(cur); cur = None
                cur = cur or []
                cur.append(r)
                if st is not None:
                    last_step = st
    if cur:
        runs.append(cur)
    out = []
    for r in runs:
        if not any(x.get('step') for x in r):
            continue
        steps = max([x.get('step', 0) for x in r] + [0])
        hit = any(x.get('event') == 'max_steps' for x in r)
        cost = 0.0
        for x in r:
            if x.get('event') == 'done':
                cost = x.get('cost_cny') or 0.0
        out.append({'steps': steps, 'hit_limit': hit, 'cost': cost,
                    'goal': (r[0].get('goal') or '')[:60]})
    return out


def main():
    days = 7
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    runs = read_runs(days)
    if not runs:
        print(f'最近 {days} 天没有可统计的运行'); return

    n = len(runs)
    hits = [r for r in runs if r['hit_limit']]
    hit_rate = len(hits) / n
    avg = sum(r['steps'] for r in runs) / n
    mx = max(r['steps'] for r in runs)
    cost = sum(r['cost'] for r in runs)

    if hit_rate > 0.10:
        verdict = f'不够 —— 撞线率 {hit_rate:.0%}，建议抬到 {max(LIMIT + 15, int(mx * 1.3))}'
    elif hit_rate >= 0.03:
        verdict = f'观察 —— 撞线率 {hit_rate:.0%}，再攒几天'
    else:
        verdict = f'够用 —— 撞线率 {hit_rate:.0%}'
    # 2026-10-29 主人定：平均步数低**不是问题**，不用为了省钱去降上限。
    #   原来这里会提示「额度偏富余」，容易诱导把上限往下砍 —— 那不是我们要的优化方向。
    #   额度留富余，是为了让复杂任务（做片子、跑 ffmpeg、上传）撞不到线。

    line = (f"| {datetime.datetime.now():%F %H:%M} | 近{days}天 | {n} | {avg:.1f} | {mx} | "
            f"{len(hits)} ({hit_rate:.0%}) | {cost:.3f} | {verdict} |")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    new = not os.path.exists(OUT)
    with open(OUT, 'a', encoding='utf-8') as f:
        if new:
            f.write('# max_steps 观测日志\n\n'
                    f'上限现值：{LIMIT}（2026-10-29 从 30 提到 45，依据：当时没依据，现在开始攒）\n\n'
                    '| 检查时间 | 窗口 | 运行数 | 平均步数 | 最高步数 | 撞上限 | 花费(元) | 结论 |\n'
                    '|---|---|---|---|---|---|---|---|\n')
        f.write(line + '\n')
    print(line)
    if hits:
        print('撞线的运行：')
        for h in hits[:5]:
            print(f"  {h['steps']} 步｜{h['goal']}")
    print(f'已写：{OUT}')


if __name__ == '__main__':
    main()
