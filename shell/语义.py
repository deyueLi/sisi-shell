#!/usr/bin/env python3
"""语义检索：把记忆从「字面对上」变成「意思对上」。

做法：
  · 用本机 ollama 的 bge-m3 把每条记忆算成 1024 维向量，缓存在 data/mem/embed.db
  · 只给新写入或改过的条目重算（按 content 的 md5 判断）
  · 查询时算一次向量，和缓存里的比余弦相似度
  · ollama 不在 / 模型没装 → 直接抛错，让调用方退回字面搜索（不许假装有结果）
"""
import os, json, math, sqlite3, hashlib, urllib.request

OLLAMA = os.environ.get('SISI_OLLAMA', 'http://<IP>:11434')
MODEL = os.environ.get('SISI_EMBED_MODEL', 'bge-m3:latest')
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get('SISI_WORKDIR') or os.path.dirname(HERE)
MEOW = os.environ.get('SISI_MEMDB') or os.path.join(os.path.dirname(DATA), 'mem', 'memory.db')
CACHE = os.environ.get('SISI_EMBED_DB') or os.path.join(os.path.dirname(MEOW), 'embed.db')
LEVELS = ['soul', 'user', 'rules', 'lesson', 'fact', 'topic', 'project']

def _h(s):
    return hashlib.md5(' '.join((s or '').split()).encode()).hexdigest()

def _embed(text):
    body = json.dumps({'model': MODEL, 'prompt': (text or '')[:2000]}).encode()
    req = urllib.request.Request(OLLAMA + '/api/embeddings', data=body,
                                 headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    v = d.get('embedding')
    if not v:
        raise RuntimeError('ollama 没给向量')
    return v

def _cache_conn():
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    c = sqlite3.connect(CACHE)
    c.execute('''create table if not exists vec(
        id text primary key, level text, hash text, vec blob, updated_at integer)''')
    c.commit()
    return c

def ensure_index(limit=None):
    """把新增/改过的记忆算成向量。返回 (新增数, 总数)。"""
    mem = sqlite3.connect(MEOW); mem.row_factory = sqlite3.Row
    ca = _cache_conn()
    have = {r[0]: r[1] for r in ca.execute('select id, hash from vec')}
    added = 0
    for lv in LEVELS:
        try:
            rows = mem.execute(f'select id, content, status from {lv}').fetchall()
        except Exception:
            continue
        for r in rows:
            if not r['id'] or not r['content']:
                continue
            h = _h(r['content'])
            if have.get(r['id']) == h:
                continue
            try:
                v = _embed(r['content'])
            except Exception:
                mem.close(); ca.close()
                raise
            ca.execute('insert or replace into vec(id, level, hash, vec, updated_at) values(?,?,?,?,'
                       'strftime("%s","now"))', (r['id'], lv, h, json.dumps(v)))
            added += 1
            if limit and added >= limit:
                ca.commit(); mem.close(); ca.close()
                return added, ca.execute('select count(*) from vec').fetchone()[0] if False else added
    ca.commit()
    total = ca.execute('select count(*) from vec').fetchone()[0]
    mem.close(); ca.close()
    return added, total

def _cos(a, b):
    s = 0.0; na = 0.0; nb = 0.0
    for x, y in zip(a, b):
        s += x * y; na += x * x; nb += y * y
    return s / (math.sqrt(na) * math.sqrt(nb) + 1e-9)

def search(query, k=8):
    """按意思找记忆。返回 [{level,id,score,text}]，找不到就空表。"""
    qv = _embed(query)
    ca = _cache_conn()
    rows = ca.execute('select id, level, vec from vec').fetchall()
    ca.close()
    scored = []
    for rid, level, blob in rows:
        try:
            v = json.loads(blob)
        except Exception:
            continue
        scored.append((_cos(qv, v), level, rid))
    scored.sort(reverse=True)
    top = scored[:k]
    mem = sqlite3.connect(MEOW); mem.row_factory = sqlite3.Row
    out = []
    for score, level, rid in top:
        try:
            r = mem.execute(f'select content, project from {level} where id=?', (rid,)).fetchone()
        except Exception:
            continue
        if not r:
            continue
        out.append({'level': level, 'id': rid, 'score': round(score, 3),
                    'project': r['project'] if 'project' in r.keys() else '',
                    'text': (r['content'] or '')[:200]})
    mem.close()
    return out

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'index':
        n, t = ensure_index()
        print(f'新建向量 {n} 条，缓存共 {t} 条')
    else:
        q = ' '.join(sys.argv[1:]) or '小红书 发布 失败'
        for h in search(q):
            print(f"{h['score']:.3f} [{h['level']}] {h['text'][:80]}")
