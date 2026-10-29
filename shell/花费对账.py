#!/usr/bin/env python3
"""花费对账：把「谁花的钱」分开算清楚。

**为什么要这个脚本**（2026-10-29 犯的错）：
我去 B站 评论区说「今天一天烧了 0.369 元，一百块够我跑两百多天」。
那个 0.369 只是壳自己的小账本（`logs/spend.json`，只记 agent.py 发起的调用）。
**主人跟我在 DSH 这边聊天的那一大块，根本不进那本账。**
账号实际花了 65.4 元。我拿局部当全部，还公开发出去了 —— 这是撒谎，不是估算。

所以这个脚本只做一件事：**把三个口径分开报，谁都不许再说「我一天花了 X 元」这种混话。**

   ① DSH 会话口径   本地会话日志里的 token 用量（主人跟我聊天、跑插件都在这）
   ② 壳口径          NAS 上 agent.py 自己记的 spend.json
   ③ 真账单          **只有 DeepSeek 控制台知道**，本地算不出来，只能标「以控制台为准」

用法：
  python3 花费对账.py              看全部
  python3 花费对账.py --days 3     只看最近 3 天
"""
import os, sys, json, glob, subprocess, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
PIN = CFG.get('price_in_per_m', 0.15)     # 元/百万 tokens（进）
POUT = CFG.get('price_out_per_m', 0.6)    # 元/百万 tokens（出）
DSH = os.environ.get('DSH_HOME', os.path.expanduser('~/.dsh'))
SESS = os.path.join(DSH, 'sessions')
ZSTD = '/opt/homebrew/bin/zstd'


def dsh_usage(days=None):
    """扫所有会话日志，按会话汇总 token。返回 [{session, day, inp, out, cache}]"""
    rows = []
    now = datetime.datetime.now()
    for f in glob.glob(os.path.join(SESS, '*', '*', 'session*.jsonl.zstd')):
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f))
        except Exception:
            continue
        if days and (now - mtime).days > days:
            continue
        try:
            raw = subprocess.run([ZSTD, '-dc', f], capture_output=True, timeout=120).stdout
            lines = raw.decode('utf-8', 'ignore').splitlines()
        except Exception:
            continue
        inp = out = cache = 0
        for ln in lines:
            if '"assistant/message"' not in ln:
                continue
            try:
                o = json.loads(ln)
            except Exception:
                continue
            u = (o.get('data') or {}).get('usage') or {}
            inp += u.get('inputTokens') or 0
            out += u.get('outputTokens') or 0
            cache += u.get('cacheReadTokens') or 0
        if inp or out or cache:
            rows.append({'file': os.path.relpath(f, SESS).split(os.sep)[0][:24],
                         'mtime': mtime.strftime('%m-%d %H:%M'),
                         'inp': inp, 'out': out, 'cache': cache})
    return rows


def shell_ledger(days=None):
    """NAS 壳自己的账（本地有副本就读副本）。"""
    for p in (os.path.join(HERE, 'logs', 'spend.json'),
              os.path.expanduser('~/.dsh/whale-work/思思/临时/work/spend.json')):
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding='utf-8'))
                if days:
                    cut = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
                    d = {k: v for k, v in d.items() if k >= cut}
                return d, p
            except Exception:
                continue
    return {}, ''


def main():
    days = None
    if '--days' in sys.argv:
        days = int(sys.argv[sys.argv.index('--days') + 1])
    rows = dsh_usage(days)
    di = sum(r['inp'] for r in rows) / 1e6
    do = sum(r['out'] for r in rows) / 1e6
    dc = sum(r['cache'] for r in rows) / 1e6
    est = di * PIN + do * POUT + dc * PIN * 0.1   # 缓存读按输入价 1 折估算
    led, lp = shell_ledger(days)

    print(f'=== 花费对账（{"全部" if not days else f"最近 {days} 天"}）===')
    print(f'① DSH 会话口径：{len(rows)} 个会话')
    print(f'   输入 {di:.2f}M｜输出 {do:.2f}M｜缓存读 {dc:.1f}M')
    print(f'   按壳的单价粗估 ≈ {est:.2f} 元（缓存按一折算，仅供量级参考）')
    print(f'② 壳口径：{sum(led.values()):.3f} 元（{len(led)} 天，来源 {lp or "未找到"}）')
    for k in sorted(led)[-5:]:
        print(f'   {k}  {led[k]:.3f} 元')
    print('③ 真账单：本地算不出来，**以 DeepSeek 控制台为准**（2026-10-29 控制台显示 65.40 元 / 4841 次请求）')
    print()
    print('大头在最上面那几个会话：')
    for r in sorted(rows, key=lambda x: -(x['inp'] + x['out'] + x['cache']))[:5]:
        print(f"   {r['mtime']}  {r['file']:<26} 输入{r['inp']/1e6:6.2f}M 输出{r['out']/1e6:5.2f}M 缓存{r['cache']/1e6:8.1f}M")


if __name__ == '__main__':
    main()
