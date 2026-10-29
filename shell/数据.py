#!/usr/bin/env python3
"""内容数据：把三条平台的真实数字收回来，和我给每条片子打的结构特征对起来。

为什么要有这个：进化层现在只会学「少调一次工具」，因为它拿到的反馈只有步骤和报错。
内容要能学，得先有「这条片子什么结构 → 用户留没留下来」这张表。
用法：python3 数据.py  （收数 + 复盘）
"""
import os, json, time, datetime, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get('SISI_WORKDIR', '$SISI_ROOT/data/work')
OUT = os.path.join(W, '内容')
FEAT = os.path.join(OUT, '特征.json')
DATA = os.path.join(OUT, '数据.jsonl')
REPORT = os.path.join(OUT, '复盘.md')
os.makedirs(OUT, exist_ok=True)

BILI_CREDS = '$SISI_ROOT/data/secrets/bili-creds.json'

def bili_stat(bv):
    try:
        d = json.load(open(BILI_CREDS))
        ck = f"SESSDATA={d['sessdata']}; bili_jct={d['bili_jct']}"
        req = urllib.request.Request(f'https://api.bilibili.com/x/web-interface/view?bvid={bv}',
                                     headers={'cookie': ck, 'user-agent': 'Mozilla/5.0'})
        r = json.load(urllib.request.urlopen(req, timeout=15))
        s = (r.get('data') or {}).get('stat') or {}
        return {'view': s.get('view'), 'like': s.get('like'), 'reply': s.get('reply'),
                'fav': s.get('favorite'), 'coin': s.get('coin'), 'share': s.get('share')}
    except Exception as e:
        return {'error': f'{type(e).__name__}'}

def hands(action, args=None):
    import sys
    sys.path.insert(0, HERE)
    import tools as T
    return T.hands(action, args or {})

def douyin():
    try:
        r = hands('douyin_stats')
        d = (r or {}).get('data') or {}
        return d.get('works') or []
    except Exception:
        return []

def load_features():
    try:
        return json.load(open(FEAT, encoding='utf-8'))
    except Exception:
        return []

def collect():
    feats = load_features()
    dy = douyin()
    rows = []
    for f in feats:
        row = dict(f, at=f'{datetime.datetime.now():%F %T}')
        if f.get('bvid'):
            row['b站'] = bili_stat(f['bvid'])
        # 抖音按日期+时长对（标题我不写死，用发布时间匹配）
        hit = None
        for w in dy:
            # 日期 + 时长 双重匹配（06/07 是同一天发的，只按日期会串号）
            if (f.get('dy_date') and w.get('date') == f['dy_date']
                    and (not f.get('时长') or w.get('dur') == f['时长'])):
                hit = w; break
        if hit:
            row['抖音'] = {k: hit.get(k) for k in ('play', 'like', 'comment', 'share', 'fav',
                                                   'finish', 'skip2', 'fans', 'state')}
        rows.append(row)
    with open(DATA, 'a', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    return rows

def avg(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 2) if xs else None

def analyze(rows):
    by_type = {}
    for r in rows:
        t = r.get('开场类型') or '未标'
        d = r.get('抖音') or {}
        by_type.setdefault(t, []).append(d)
    lines = [f'# 内容复盘 {datetime.datetime.now():%F %T}', '',
             '| 集 | 开场类型 | 首句 | 时长 | 抖音播放 | 2秒跳出 | 完播 | B站播放 |',
             '|---|---|---|---|---|---|---|---|']
    for r in rows:
        d = r.get('抖音') or {}
        b = r.get('b站') or {}
        lines.append(f"| {r.get('id')} | {r.get('开场类型','')} | {str(r.get('首句',''))[:16]} | "
                     f"{r.get('时长','')} | {d.get('play','')} | {d.get('skip2','')}% | "
                     f"{d.get('finish','')}% | {b.get('view','')} |")
    lines += ['', '## 按开场类型取平均（数字够多才有意义）', '']
    for t, ds in by_type.items():
        lines.append(f"- {t}：{len(ds)} 条，平均 2 秒跳出 {avg([d.get('skip2') for d in ds])}%，"
                     f"平均播放 {avg([d.get('play') for d in ds])}，平均完播 {avg([d.get('finish') for d in ds])}%")
    lines += ['', '## 现在能得出的结论', '']
    good = [d for d in (r.get('抖音') or {} for r in rows) if isinstance(d.get('skip2'), (int, float)) and d['skip2'] > 0]
    if len(good) < 3:
        lines.append('- 样本太少（不到 3 条有数据的），现在下结论等于瞎猜。')
    else:
        best = min(good, key=lambda d: d['skip2'])
        worst = max(good, key=lambda d: d['skip2'])
        lines.append(f"- 2 秒跳出最低 {best['skip2']}%，最高 {worst['skip2']}%，差 {round(worst['skip2']-best['skip2'],1)} 个百分点")
        lines.append('- 这个差如果一直存在，说明开场就在决定生死；如果两条差在 10 个点内，说明开场不是主因。')
    open(REPORT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return '\n'.join(lines)

if __name__ == '__main__':
    rows = collect()
    print(analyze(rows))
