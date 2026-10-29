#!/usr/bin/env python3
"""每晚对账：把她这一天的账，摊成一张纸，供两边核对。

主人 2026-10-29 定：「每天晚上 12 点你需要和她对一遍」。
为什么要有：今晚就出过三次「两边说法对不上」——
  · 她说「08 还没发出去」，可 B站 上稿子是在的（她指的是重发失败）；
  · 我拿壳的 spend.json 当全天花销，实际账号花了 65 倍；
  · 她主动消息走微信、我的推送走飞书，两条路互不相干。
对账不是寒暄，是**把口径对齐**。

产出：$SISI_ROOT/data/work/对账/<日期>-她.md
用法：python3 对账.py [--days 1]
"""
import os, sys, json, glob, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get('SISI_WORKDIR', os.path.dirname(HERE))
OUT = os.path.join(W, '对账')
LOGS = os.path.join(HERE, 'logs')
TODAY = datetime.date.today().isoformat()


def read_json(p, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default


def runs_today(day=TODAY):
    """今天的运行：次数、平均步数、最高步数、撞上限次数、花费。"""
    f = os.path.join(LOGS, day + '.jsonl')
    if not os.path.exists(f):
        return {'n': 0, 'avg': 0, 'max': 0, 'hit': 0, 'cost': 0.0}
    recs, cur, last = [], None, None
    for ln in open(f, encoding='utf-8'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        st = r.get('step')
        if (r.get('goal') is not None or (st == 1 and last not in (None, 0) and last > 1)) and cur:
            recs.append(cur); cur = None
        cur = cur or []
        cur.append(r)
        if st is not None:
            last = st
    if cur:
        recs.append(cur)
    runs = [r for r in recs if any(x.get('step') for x in r)]
    if not runs:
        return {'n': 0, 'avg': 0, 'max': 0, 'hit': 0, 'cost': 0.0}
    steps = [max(x.get('step', 0) for x in r) for r in runs]
    hit = sum(1 for r in runs if any(x.get('event') == 'max_steps' for x in r))
    cost = sum((x.get('cost_cny') or 0) for r in runs for x in r if x.get('event') == 'done')
    return {'n': len(runs), 'avg': round(sum(steps) / len(steps), 1), 'max': max(steps),
            'hit': hit, 'cost': round(cost, 4)}


def failures_today():
    """今天真正失败/被拦的调用（不是每条 error，去重）。"""
    f = os.path.join(LOGS, TODAY + '.jsonl')
    out = []
    if not os.path.exists(f):
        return out
    for ln in open(f, encoding='utf-8'):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get('blocked'):
            out.append(f"被拦：{r.get('tool')}（{str(r.get('blocked'))[:60]}）")
        elif r.get('error'):
            out.append(f"出错：{r.get('tool')}（{str(r.get('error'))[:80]}）")
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x); uniq.append(x)
    return uniq[-8:]


def todos():
    d = read_json(os.path.join(W, 'todo.json'), [])
    items = d if isinstance(d, list) else (d.get('items') or [])
    return [str((x.get('text') or x.get('title') or ''))[:70] for x in items][:10]


def main():
    os.makedirs(OUT, exist_ok=True)
    run = runs_today()
    fails = failures_today()
    td = todos()
    spend = read_json(os.path.join(HERE, 'logs', 'spend.json'), {})
    bal = read_json(os.path.join(W, '知识', '余额台账.jsonl'), None)
    bal_last = None
    p = os.path.join(W, '知识', '余额台账.jsonl')
    if os.path.exists(p):
        lines = [l for l in open(p, encoding='utf-8') if l.strip()]
        if lines:
            try:
                bal_last = json.loads(lines[-1])
            except Exception:
                pass
    lines = [
        f'# 她那本账 · {TODAY}',
        '',
        '## 运行',
        f"- 次数 {run['n']}｜平均 {run['avg']} 步｜最高 {run['max']} 步｜撞上限 {run['hit']} 次｜花费 {run['cost']} 元",
        f"- 壳自己记的花费（只含壳发起的调用）：{round(sum(spend.values()), 4) if spend else 0} 元",
    ]
    if bal_last:
        lines.append(f"- 账号余额（最后一次记）：{bal_last.get('cny')} 元 @ {bal_last.get('at')}")
    lines += ['', '## 失败 / 被拦']
    lines += [f'- {x}' for x in fails] or ['- 无']
    lines += ['', '## 待办']
    lines += [f'- {x}' for x in td] or ['- 空']
    # 今天新增的内容数据
    dj = os.path.join(W, '内容', '数据.jsonl')
    if os.path.exists(dj):
        rows = []
        for ln in open(dj, encoding='utf-8'):
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if str(r.get('at', '')).startswith(TODAY):
                rows.append(r)
        if rows:
            lines += ['', '## 今天记进来的数据']
            for r in rows[:6]:
                lines.append(f"- {str(r.get('title'))[:26]}｜播 {r.get('play')}｜2秒跳出 {r.get('bounce2s_pct')}%｜完播 {r.get('finish_pct')}%")
    out = os.path.join(OUT, f'{TODAY}-她.md')
    open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(out)
    print('\n'.join(lines[:8]))


if __name__ == '__main__':
    main()
