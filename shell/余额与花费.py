#!/usr/bin/env python3
"""余额台账：用官方 API 每天记一次余额，靠差额算真实花费。

**为什么不再猜钱**（2026-10-29 教训）：
我把壳自己的 spend.json 当成全天花销，在评论区报了「0.369 元／够跑两百多天」，实际账号花了 65.4 元。
壳的账只记壳发起的调用；DSH 会话那一大块不在里头。

**为什么不用网页的 usage 页**：
platform.deepseek.com/usage 是个 SPA，接口路径没公开，用浏览器 cookie 直接 curl 会被 WAF 挡（Request Blocked）。
但**官方 API 有余额接口**：GET https://api.deepseek.com/user/balance（Bearer key，免费、无副作用）。
所以：**每天记一次余额，用「上次 - 这次」= 这段时间真花的钱。** 充值会打断这个减法，所以台账里也记充值。

用法：
  python3 余额与花费.py           查一次并记一笔
  python3 余额与花费.py --show    只看台账，不查询
"""
import os, sys, json, time, urllib.request, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get('SISI_WORKDIR', os.path.dirname(HERE))
LEDGER = os.path.join(W, '知识', '余额台账.jsonl')
KEYS = [os.path.join(HERE, '..', '.deepseek-key'),
        os.path.expanduser('~/.dsh/whale-work/思思/.deepseek-key'),
        os.environ.get('SISI_KEY_FILE', '')]


def api_key():
    for p in KEYS:
        if p and os.path.exists(p):
            k = open(p, encoding='utf-8').read().strip()
            if k:
                return k
    raise SystemExit('找不到 API key（SISI_KEY_FILE 或 思思/.deepseek-key）')


def balance():
    req = urllib.request.Request('https://api.deepseek.com/user/balance',
                                 headers={'Authorization': 'Bearer ' + api_key(),
                                          'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode())
    info = (d.get('balance_infos') or [{}])[0]
    return {'available': d.get('is_available'), 'cny': float(info.get('total_balance') or 0),
            'granted': float(info.get('granted_balance') or 0),
            'topped': float(info.get('topped_up_balance') or 0)}


def load():
    out = []
    if os.path.exists(LEDGER):
        for ln in open(LEDGER, encoding='utf-8'):
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    return out


def show():
    rows = load()
    if not rows:
        print('台账空'); return
    print(f'{"时间":<20}{"余额":>8}{"本次花费":>10}')
    prev = None
    for r in rows[-12:]:
        spend = ''
        if prev is not None:
            delta = prev - r['cny']
            # 余额变多 = 充值了，不算花费
            spend = f'{delta:+.2f}' if abs(delta) > 1e-9 else '0.00'
        print(f"{r['at']:<20}{r['cny']:>8.2f}{spend:>10}")
        prev = r['cny']
    if len(rows) >= 2:
        span = rows[-1]['cny'] - rows[0]['cny']
        days = max(1, (datetime.datetime.fromisoformat(rows[-1]['at']) -
                       datetime.datetime.fromisoformat(rows[0]['at'])).days or 1)
        print(f'\n台账跨度 {days} 天，余额净变 {span:+.2f} 元（负数=净花费，正数=充过钱）')


def main():
    if '--show' in sys.argv:
        show(); return
    b = balance()
    rec = {'at': datetime.datetime.now().isoformat(timespec='seconds'), **b}
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f"余额 {b['cny']:.2f} 元（充值余额 {b['topped']:.2f}｜赠送 {b['granted']:.2f}）｜可用 {b['available']}")
    rows = load()
    if len(rows) >= 2:
        d = rows[-2]['cny'] - b['cny']
        print(f'距上次记录（{rows[-2]["at"]}）花了 {d:+.2f} 元' + ('（充过值，不算花费）' if d < 0 else ''))
    print(f'已记：{LEDGER}')


if __name__ == '__main__':
    main()
