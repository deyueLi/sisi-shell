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
    # 2026-10-30 跟 MemOS 学的：向量之外再来一路字面检索（FTS5 + BM25）。
    # 专有名词、编号、英文缩写这类「字面对得上但语义不近」的查询，向量会漏，BM25 不漏。
    try:
        c.execute('''create virtual table if not exists fts using fts5(
            id unindexed, level unindexed, content, tokenize='unicode61')''')
    except Exception:
        pass   # 老 sqlite 没有 fts5 就只走向量，不假装有
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
    try:
        _fts_sync(ca, mem, True)
    except Exception:
        pass
    total = ca.execute('select count(*) from vec').fetchone()[0]
    mem.close(); ca.close()
    return added, total

def _fts_sync(ca, mem, have_fts):
    """把新增/改过的记忆同步进 FTS 表。"""
    if not have_fts:
        return
    rows = ca.execute('select id from fts').fetchall()
    indexed = {r[0] for r in rows}
    for lv in LEVELS:
        try:
            for r in mem.execute(f'select id, content, status from {lv}').fetchall():
                if not r['id'] or not r['content']:
                    continue
                if r['id'] in indexed:
                    continue
                ca.execute('insert into fts(id, level, content) values(?,?,?)',
                           (r['id'], lv, r['content']))
        except Exception:
            continue
    ca.commit()


def _fts_search(ca, query, k=20):
    """BM25 排序的字面检索。fts5 不可用就返回空。"""
    try:
        rows = ca.execute(
            'select id, level, bm25(fts) as s from fts where fts match ? order by s limit ?',
            (_fts_query(query), k)).fetchall()
    except Exception:
        return []
    return [(r[0], r[1]) for r in rows]


def _fts_query(q):
    """把一句人话变成 fts5 能吃的查询：拆词 + 加引号，避免语法错。"""
    import re as _re
    words = [w for w in _re.split(r'[\s，。,.!?；;：:、]+', (q or '')) if len(w) >= 2]
    if not words:
        return '""'
    return ' OR '.join('"' + w.replace('"', '') + '"' for w in words[:8])


def _cos(a, b):
    s = 0.0; na = 0.0; nb = 0.0
    for x, y in zip(a, b):
        s += x * y; na += x * x; nb += y * y
    return s / (math.sqrt(na) * math.sqrt(nb) + 1e-9)

def search(query, k=8):
    """按意思找记忆 + 按字面找，两路用 RRF 融合。

    2026-10-30 改：原来是「纯向量」。向量对「专有名词、编号、英文缩写」不敏感
    （人问 SKILLOPT、BV1Ffsf6NEot 这种，向量可能排在很后面），BM25 反而是强项。
    融合用 RRF（rank fusion，只吃名次不吃原始分），比直接加权稳。
    """
    qv = _embed(query)
    ca = _cache_conn()
    rows = ca.execute('select id, level, vec from vec').fetchall()
    vec_rank = []
    for rid, level, blob in rows:
        try:
            v = json.loads(blob)
        except Exception:
            continue
        vec_rank.append((_cos(qv, v), level, rid))
    vec_rank.sort(reverse=True)
    vec_rank = vec_rank[:40]
    lit_rank = _fts_search(ca, query, k=40)
    ca.close()
    # RRF：score = Σ 1/(60 + 名次)
    fused = {}
    for i, (score, level, rid) in enumerate(vec_rank):
        fused[(level, rid)] = fused.get((level, rid), 0.0) + 1.0 / (60 + i)
    for i, (rid, level) in enumerate(lit_rank):
        fused[(level, rid)] = fused.get((level, rid), 0.0) + 1.0 / (60 + i)
    if not fused:
        return []
    order = sorted(fused.items(), key=lambda kv: -kv[1])[:k]
    top = [(min(1.0, sc * 30), lv, rid) for (lv, rid), sc in order]
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

def near_duplicate(content, thr=0.92, budget_s=1.5):
    """找「意思几乎一样」的已有记忆。返回 (id, level, 相似度) 或 None。

    为什么要有：md5 只能挡「一字不差」，挡不住「同一条经验换个说法写三遍」。
    MemOS 的 smart dedup 就是干这个的。给个时间预算，超时就放弃（不拖慢写入）。
    """
    import time as _t
    t0 = _t.time()
    try:
        qv = _embed(content)
    except Exception:
        return None
    ca = _cache_conn()
    best = None
    for rid, level, blob in ca.execute('select id, level, vec from vec').fetchall():
        if _t.time() - t0 > budget_s:
            break
        try:
            v = json.loads(blob)
        except Exception:
            continue
        score = _cos(qv, v)
        if score >= thr and (best is None or score > best[2]):
            best = (rid, level, round(score, 3))
    ca.close()
    return best


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'index':
        n, t = ensure_index()
        print(f'新建向量 {n} 条，缓存共 {t} 条')
    else:
        q = ' '.join(sys.argv[1:]) or '小红书 发布 失败'
        for h in search(q):
            print(f"{h['score']:.3f} [{h['level']}] {h['text'][:80]}")
