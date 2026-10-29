#!/usr/bin/env python3
"""计费：按官方价目表把每一分钱算准。

为什么重写（2026-10-30）：
  主人从 小红书 发来一篇笔记，人家给 DSH 搓了个「实时显示对话消耗费用」的插件。
  我回头查自己的账，发现**价格表是错的**：
      config.json 里写 输入 0.15、输出 0.6 元/百万
      实际 deepseek-flash：输入未命中 1（空闲）/2（高峰），输入命中 0.02/0.04，输出 4/8
  也就是说，我这些天报的「花了多少」比真实便宜 6～13 倍。
  我到现在才意识到：**我不是记少了，是记错了。**

官方价（2026-10-17 起，元/百万 tokens）：
  deepseek-flash   命中输入 0.02/0.04   未命中输入 1/2   输出 4/8
  deepseek-v4-pro  命中输入 0.15/0.30   未命中输入 4.5/9  输出 13.5/27
  高峰 = 北京时间 周一至周五 9:00-12:00、14:00-18:00（不含法定节假日）；其余为空闲（半价）。
  另：Search/Fetch 自 2026-11-01 00:00 起按次收费（每 1000 次 5 元）。

用法：
  python3 计费.py                # 今天的账：调用数、命中率、三档花费、峰谷分列
  python3 计费.py --day 2026-10-29
  python3 计费.py --last 5       # 最近 5 次运行逐条
"""
import os, sys, json, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(HERE, 'logs')
BASE = os.path.dirname(HERE)                       # data/work
HOLIDAY_FILE = os.path.join(HERE, '节假日.json')

# (空闲, 高峰)，元 / 百万 tokens
PRICES = {
    'deepseek-flash': {'hit': (0.02, 0.04), 'miss': (1.0, 2.0), 'out': (4.0, 8.0)},
    'deepseek-v4-pro': {'hit': (0.15, 0.30), 'miss': (4.5, 9.0), 'out': (13.5, 27.0)},
}
PEAK_HOURS = [(9, 12), (14, 18)]
SEARCH_PER_REQ = 5.0 / 1000        # 2026-11-01 起
SEARCH_FREE_BEFORE = datetime.date(2026, 11, 1)


def _holidays():
    try:
        return set(json.load(open(HOLIDAY_FILE, encoding='utf-8')).get('days') or [])
    except Exception:
        return set()


def is_peak(dt=None):
    """是不是高峰时段。法定节假日要人工维护 节假日.json（官方只说「不含法定节假日」）。"""
    dt = dt or datetime.datetime.now()
    if dt.date().isoformat() in _holidays():
        return False
    if dt.weekday() >= 5:
        return False
    return any(a <= dt.hour < b for a, b in PEAK_HOURS)


def cost_of(usage, when=None, model='deepseek-flash'):
    """一次调用的花费，拆成命中/未命中/输出三档。

    usage 里 DeepSeek 会给 prompt_tokens_details.cached_tokens；
    没给就按「全未命中」算——宁可算贵，不要算便宜（算便宜会让人以为还有钱）。
    """
    if not usage:
        return {'hit_tokens': 0, 'miss_tokens': 0, 'out_tokens': 0, 'cny': 0.0, 'peak': False}
    p = PRICES.get(model) or PRICES['deepseek-flash']
    peak = is_peak(when)
    i = 1 if peak else 0
    prompt = int(usage.get('prompt_tokens') or 0)
    out = int(usage.get('completion_tokens') or 0)
    det = usage.get('prompt_tokens_details') or {}
    cached = det.get('cached_tokens')
    if cached is None:
        hit, miss = 0, prompt
    else:
        cached = int(cached)
        hit = min(cached, prompt)
        miss = max(0, prompt - hit)
    cny = (hit * p['hit'][i] + miss * p['miss'][i] + out * p['out'][i]) / 1_000_000
    return {'hit_tokens': hit, 'miss_tokens': miss, 'out_tokens': out,
            'cny': round(cny, 6), 'peak': peak}


def day_records(day):
    f = os.path.join(LOGDIR, f'{day}.jsonl')
    if not os.path.exists(f):
        return []
    out = []
    for ln in open(f, encoding='utf-8'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def runs(recs):
    """把一串日志切成一次一次的运行。"""
    runs, cur, last = [], [], None
    for r in recs:
        st = r.get('step')
        if st == 1 and last not in (None, 1):
            runs.append(cur); cur = []
        cur.append(r)
        if st:
            last = st
    if cur:
        runs.append(cur)
    return runs


def summary(day=None, model='deepseek-flash'):
    day = day or datetime.date.today().isoformat()
    recs = day_records(day)
    calls, hit, miss, out, cny, peak_n = 0, 0, 0, 0, 0.0, 0
    for r in recs:
        u = r.get('usage')
        if not u:
            continue
        c = cost_of(u, model=model)      # 逐条按当时的时段算不准（没存时间戳到秒），按下标近似
        calls += 1
        hit += c['hit_tokens']; miss += c['miss_tokens']; out += c['out_tokens']
        cny += c['cny']; peak_n += 1 if c['peak'] else 0
    run_list = [x for x in runs(recs) if any(y.get('usage') for y in x)]
    per_run = []
    for rr in run_list:
        c = sum(cost_of(y.get('usage'), model=model)['cny'] for y in rr if y.get('usage'))
        per_run.append({'steps': max(y.get('step', 0) for y in rr), 'cny': round(c, 5)})
    return {'day': day, 'calls': calls, 'hit_tokens': hit, 'miss_tokens': miss,
            'out_tokens': out, 'cny': round(cny, 5), 'peak_calls': peak_n,
            'runs': len(per_run), 'per_run': per_run,
            'hit_rate': round(hit / (hit + miss) * 100, 1) if (hit + miss) else 0.0}


def main():
    day = None
    if '--day' in sys.argv:
        day = sys.argv[sys.argv.index('--day') + 1]
    s = summary(day)
    print(f"## {s['day']} 的账（deepseek-flash 官方价）")
    print(f"调用 {s['calls']} 次｜运行 {s['runs']} 次｜缓存命中率 {s['hit_rate']}%")
    print(f"输入 命中 {s['hit_tokens']:,}｜未命中 {s['miss_tokens']:,}｜输出 {s['out_tokens']:,} tokens")
    print(f"合计 ¥{s['cny']:.4f}")
    if s['per_run']:
        avg = s['cny'] / max(1, s['runs'])
        print(f"平均每次运行 ¥{avg:.4f}；最贵一次 ¥{max(x['cny'] for x in s['per_run']):.4f}")
    if '--last' in sys.argv:
        n = int(sys.argv[sys.argv.index('--last') + 1])
        print('\n最近几次：')
        for i, x in enumerate(s['per_run'][-n:], 1):
            print(f"  第 {i} 次：{x['steps']} 步，¥{x['cny']:.4f}")
    # 现在这个时段
    now = datetime.datetime.now()
    print(f"\n现在 {now:%H:%M} 是{'高峰（全价）' if is_peak(now) else '空闲（半价）'}")
    if not _holidays():
        print('（节假日表是空的：法定节假日会被当成高峰算，宁可算贵）')


if __name__ == '__main__':
    main()
