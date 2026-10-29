#!/usr/bin/env python3
"""每日巡览：八平台各逛一圈，按「条目」去重，挑真值得学的，写一份日报。

主人 2026-10-29 定的：
  · GitHub / YouTube / B站 / V2EX / 网页 / 小红书 / X / Reddit —— 每天都要去逛
  · 去重要按**条目**（同一支视频、同一篇文章不看第二遍），不能按「同类」一刀切
      → 所以这里只认条目 id（BV 号 / 仓库名 / 笔记 id / 网址…），不认关键词、不认主题

数据放哪：
  data/work/巡览-已看.json     条目 id 台账（去重就靠它）
  data/work/知识/每日巡览-<日期>.md   当天日报

用法：
  python3 每日巡览.py            逛一圈，出日报
  python3 每日巡览.py --dry      只列候选，不写文件
  python3 每日巡览.py --days 3   台账里超过 N 天的条目不再拦（内容可能更新了）
"""
import os, sys, json, time, datetime, subprocess, re

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get('SISI_WORKDIR', os.path.dirname(HERE))
# 台账和学习共用一份：逛到的条目一律记进 已学.json 的 items，学的时候不会再读第二遍
LEDGER = os.path.join(W, '已学.json')
OUTDIR = os.path.join(W, '知识')
AR = os.path.expanduser('~/.local/bin/agent-reach')

# 需要翻墙才通的平台（主人 2026-10-29 说：这三个得有 VPN）
NEEDS_PROXY = {'youtube', 'twitter'}   # reddit 直连就能开（主人 2026-10-29 实测）
# 代理地址：优先环境变量，其次配置文件 临时/work/巡览-配置.json 的 proxy 字段。
# 配了就走代理；没配就**直接跳过这三家**，别每次都白等 20 秒再超时。
def proxy_url():
    for k in ('SISI_PROXY', 'HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        v = os.environ.get(k)
        if v:
            return v
    try:
        cfg = json.load(open(os.path.join(W, '巡览-配置.json'), encoding='utf-8'))
        v = (cfg.get('proxy') or '').strip()
        if v:
            return v
    except Exception:
        pass
    # 自动探测：FlClash 的混合端口就是 7890，开着就直接用，不用手填
    import socket
    for port in (7890, 7891, 7897, 1080, 6152):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.6):
                return f'http://127.0.0.1:{port}'
        except Exception:
            continue
    return ''

# 每个平台逛什么（词是「去哪找」，不是「学什么」——学什么由判断那一步定）
PLAN = [
    ('github', '搜索', ['agent self-improvement', 'llm memory system', 'video generation pipeline']),
    ('youtube', '搜索', ['AI agent tutorial 2026', 'short video storytelling']),
    ('bilibili', '搜索', ['一分钟 故事 视频', 'AI agent 实战']),
    ('v2ex', '热帖', []),
    ('web', '搜索', ['AI agent 工程 实践 2026']),
    ('xiaohongshu', '搜索', ['短视频 起号 经验']),
    ('twitter', '搜索', ['agent skills self-evolving']),
    ('reddit', '搜索', ['self improving agent']),
]


def load_ledger():
    try:
        d = json.load(open(LEDGER, encoding='utf-8'))
        if 'items' in d and isinstance(d['items'], list):
            d['items'] = {k: {'at': 0} for k in d['items']}   # 兼容学习.py 的列表格式
        d.setdefault('items', {})
        return d
    except Exception:
        return {'items': {}}


def save_ledger(d):
    # 写回时同时保留 list 形式（学习.py 认 list），两个脚本共用一份台账
    d['items_list'] = list(d['items'].keys())[-2000:]
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    json.dump(d, open(LEDGER, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def run_ar(channel, action, args):
    if not os.path.exists(AR):
        return {'ok': False, 'error': {'message': '没装 agent-reach'}}
    env = dict(os.environ)
    if channel in NEEDS_PROXY:
        px = proxy_url()
        if not px:
            return {'ok': False, 'error': {'code': 'NEED_PROXY',
                                           'message': '这个平台要翻墙，没配代理（跳过，不白等）'}}
        env.update({'HTTPS_PROXY': px, 'HTTP_PROXY': px, 'ALL_PROXY': px,
                    'https_proxy': px, 'http_proxy': px, 'all_proxy': px})
    cmd = [AR, channel, action] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
        return json.loads(r.stdout or '{}')
    except Exception as e:
        return {'ok': False, 'error': {'message': f'{type(e).__name__}: {e}'}}


def item_key(channel, it):
    u = it.get('url') or ''
    if channel == 'bilibili':
        m = re.search(r'(BV[0-9A-Za-z]+)', u) or re.search(r'(BV[0-9A-Za-z]+)', it.get('id') or '')
        return 'bv:' + (m.group(1) if m else u)
    if channel == 'github':
        return 'gh:' + (it.get('name') or u).lower().replace('https://github.com/', '')
    if channel == 'youtube':
        m = re.search(r'[?&]v=([\w-]{6,})', u)
        return 'yt:' + (m.group(1) if m else (it.get('id') or u))
    if channel == 'xiaohongshu':
        m = re.search(r'/(?:item|explore|discovery/item)/([0-9a-f]{16,})', u)
        return 'xhs:' + (m.group(1) if m else u)
    if channel == 'v2ex':
        m = re.search(r'/t/(\d+)', u)
        return 'v2:' + (m.group(1) if m else u)
    if channel == 'twitter':
        return 'tw:' + u.rstrip('/').split('/')[-1]
    if channel == 'reddit':
        return 'rd:' + (u.split('/comments/')[-1][:24] if '/comments/' in u else u)
    return 'web:' + u.split('?')[0]


def sweep(channel, action, queries, ledger, keep_days=90):
    """逛一个平台，返回 (新条目, 跳过数, 报错)。"""
    fresh, skipped, err = [], 0, ''
    seen = ledger['items']
    now = time.time()
    if action == '热帖':
        res = run_ar(channel, 'hot', [])
    else:
        res = {'ok': False}
        for q in queries:
            res = run_ar(channel, 'search', [q, '--limit', '5'])
            if res.get('ok'):
                break
    if not res.get('ok'):
        e = (res.get('error') or {})
        return [], 0, f"{e.get('code', '?')}: {(e.get('message') or '')[:80]}"
    for it in (res.get('items') or [])[:8]:
        k = item_key(channel, it)
        hit = seen.get(k)
        if hit and (now - float(hit.get('at', 0))) < keep_days * 86400:
            skipped += 1
            continue
        fresh.append({'key': k, 'title': (it.get('title') or '')[:90],
                      'url': it.get('url') or '', 'author': (it.get('author') or '')[:30],
                      'text': (it.get('text') or '')[:200]})
    return fresh, skipped, err


def main():
    dry = '--dry' in sys.argv
    keep_days = 90
    if '--days' in sys.argv:
        keep_days = int(sys.argv[sys.argv.index('--days') + 1])
    ledger = load_ledger()
    rows, total_new, total_skip = [], 0, 0
    for channel, action, queries in PLAN:
        fresh, skipped, err = sweep(channel, action, queries, ledger, keep_days)
        total_new += len(fresh); total_skip += skipped
        rows.append({'channel': channel, 'new': fresh, 'skipped': skipped, 'error': err})
        print(f'{channel:<12} 新 {len(fresh)}｜跳过 {skipped}｜{err[:60]}', flush=True)
        if not dry:
            for f in fresh:
                ledger['items'][f['key']] = {'at': time.time(), 'title': f['title'], 'channel': channel}
    if dry:
        print(json.dumps(rows, ensure_ascii=False, indent=1)[:2000]); return

    # 台账瘦身：超过 4000 条就丢最老的
    if len(ledger['items']) > 4000:
        old = sorted(ledger['items'].items(), key=lambda kv: kv[1].get('at', 0))
        for k, _ in old[:len(ledger['items']) - 4000]:
            del ledger['items'][k]
    # 同步成学习.py 认的 list 格式（同一份台账，两个入口）
    ledger['items_list'] = list(ledger['items'].keys())[-2000:]
    ledger['items'] = ledger['items_list']
    save_ledger(ledger)

    day = datetime.date.today().isoformat()
    os.makedirs(OUTDIR, exist_ok=True)
    p = os.path.join(OUTDIR, f'每日巡览-{day}.md')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(f'# 每日巡览 · {day}\n\n新 {total_new} 条｜跳过（看过）{total_skip} 条\n\n')
        for r in rows:
            f.write(f'## {r["channel"]}\n\n')
            if r['error']:
                f.write(f'> 没逛成：{r["error"]}\n\n')
            if not r['new']:
                f.write('（没有新条目）\n\n'); continue
            for it in r['new']:
                f.write(f"- [{it['title'] or '（无标题）'}]({it['url']})  {('- ' + it['author']) if it['author'] else ''}\n")
                if it['text']:
                    f.write(f"  {it['text'][:160]}\n")
            f.write('\n')
    print(f'日报：{p}｜新 {total_new}｜跳过 {total_skip}')


if __name__ == '__main__':
    main()
