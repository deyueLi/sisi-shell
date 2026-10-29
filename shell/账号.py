"""B站 和 GitHub 的只读能力（2026-10-29 主人给账号密码后放开）

只用**读接口**：
  · B站：用 cookie 读视频信息、评论、搜索——不发布、不点赞、不关注。
  · GitHub：用 token 读仓库、代码、issue——不 push、不改别人的东西。

想写（发视频/发评论/建仓库）必须回到 Mac 上跑，那有单独的发布脚本和审核。
"""
import os, json, urllib.request, urllib.parse

W = os.environ.get('SISI_WORKDIR') or os.path.dirname(os.path.abspath(__file__))
SECRETS = os.path.join(os.path.dirname(W), 'secrets') if os.path.isdir(os.path.dirname(W)) else os.path.join(W, 'secrets')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'

def _bili_cookie():
    p = os.path.join(SECRETS, 'bili-creds.json')
    d = json.load(open(p, encoding='utf-8'))
    return f"SESSDATA={d['sessdata']}; bili_jct={d['bili_jct']}; buvid3={d.get('buvid3','')}"

def _gh_token():
    return open(os.path.join(SECRETS, 'github-token'), encoding='utf-8').read().strip()

def _get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {'user-agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', errors='replace'))

# ---------------- B站（只读） ----------------
def bili_view(bvid):
    d = _get(f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}',
             {'user-agent': UA, 'cookie': _bili_cookie()})
    if d.get('code') != 0:
        return {'ok': False, 'error': d.get('message'), 'code': d.get('code')}
    v = d['data']; s = v.get('stat') or {}
    return {'ok': True, 'bvid': bvid, 'title': v.get('title'), 'desc': (v.get('desc') or '')[:500],
            'duration': v.get('duration'), 'owner': (v.get('owner') or {}).get('name'),
            'stat': {k: s.get(k) for k in ('view', 'like', 'reply', 'favorite', 'coin', 'danmaku')},
            'cid': v.get('cid'), 'aid': v.get('aid')}

def bili_comments(bvid, n=12):
    v = bili_view(bvid)
    if not v.get('ok'): return v
    d = _get(f"https://api.bilibili.com/x/v2/reply?type=1&oid={v['aid']}&pn=1&ps={n}&sort=2",
             {'user-agent': UA, 'cookie': _bili_cookie()})
    out = []
    for r in ((d.get('data') or {}).get('replies') or [])[:n]:
        out.append({'user': (r.get('member') or {}).get('uname'),
                    'like': r.get('like'), 'text': (r.get('content') or {}).get('message', '')[:200]})
    return {'ok': True, 'bvid': bvid, 'n': len(out), 'comments': out}

def bili_search(keyword, n=8):
    q = urllib.parse.quote(keyword)
    d = _get(f'https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={q}&page=1',
             {'user-agent': UA, 'cookie': _bili_cookie(), 'referer': 'https://search.bilibili.com/'})
    if d.get('code') != 0:
        return {'ok': False, 'error': d.get('message')}
    out = []
    for v in ((d.get('data') or {}).get('result') or [])[:n]:
        out.append({'bvid': v.get('bvid'), 'title': (v.get('title') or '').replace('<em class="keyword">', '').replace('</em>', ''),
                    'author': v.get('author'), 'play': v.get('play'), 'danmaku': v.get('video_review')})
    return {'ok': True, 'keyword': keyword, 'n': len(out), 'results': out}

def bili_subtitle(bvid):
    """取官方字幕/CC（有就返回文本，没就说明没有）。"""
    v = bili_view(bvid)
    if not v.get('ok'): return v
    d = _get(f"https://api.bilibili.com/x/player/wbi/v2?bvid={bvid}&cid={v['cid']}",
             {'user-agent': UA, 'cookie': _bili_cookie(), 'referer': f'https://www.bilibili.com/video/{bvid}/'})
    subs = (((d.get('data') or {}).get('subtitle') or {}).get('subtitles') or [])
    if not subs:
        return {'ok': True, 'bvid': bvid, 'subtitle': None, 'note': '这条没有字幕'}
    u = subs[0].get('subtitle_url') or ''
    if u.startswith('//'): u = 'https:' + u
    s = _get(u, {'user-agent': UA})
    text = ' '.join(x.get('content', '') for x in (s.get('body') or []))
    return {'ok': True, 'bvid': bvid, 'lines': len(s.get('body') or []), 'text': text[:6000]}

# ---------------- GitHub（只读） ----------------
def github_search(q, kind='repositories', n=6):
    h = {'authorization': 'Bearer ' + _gh_token(), 'user-agent': UA, 'accept': 'application/vnd.github+json'}
    d = _get(f'https://api.github.com/search/{kind}?q={urllib.parse.quote(q)}&per_page={n}', h)
    if 'items' not in d:
        return {'ok': False, 'error': d.get('message', 'query failed')}
    out = []
    for it in d['items'][:n]:
        out.append({'name': it.get('full_name') or it.get('name'), 'stars': it.get('stargazers_count'),
                    'desc': (it.get('description') or '')[:160], 'url': it.get('html_url')})
    return {'ok': True, 'kind': kind, 'n': len(out), 'results': out}

def github_file(repo, path, ref='main'):
    h = {'authorization': 'Bearer ' + _gh_token(), 'user-agent': UA, 'accept': 'application/vnd.github.raw'}
    try:
        req = urllib.request.Request(f'https://api.github.com/repos/{repo}/contents/{path}?ref={ref}', headers=h)
        with urllib.request.urlopen(req, timeout=25) as r:
            txt = r.read().decode('utf-8', errors='replace')
        return {'ok': True, 'repo': repo, 'path': path, 'chars': len(txt), 'text': txt[:8000]}
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}
