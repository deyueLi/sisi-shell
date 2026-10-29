#!/usr/bin/env python3
"""自主学习：去 GitHub 和 B站 找 AI / 技术内容，判断「对我有没有用、能不能让我变强」，
有用就升级自己——写规则、装包、或者干脆给自己写个新功能。

一条完整的循环：
  查（GitHub 仓库/代码 + B站技术视频字幕）
  → 判（模型：这条对「做内容 + 当 agent」有没有用？能落地成什么？）
  → 试（能用现在的能力做到吗？不能就写功能）
  → 装（备份 → 落文件 → 语法/试跑 → 失败就删）
  → 记（知识/学习日志.md + 升级提案登记，可回滚）

用法：
  python3 学习.py            查一遍，只出提案不落地
  python3 学习.py --yes      自己判、自己落地（无人值守）
"""
import os, sys, json, time, datetime, subprocess, ast as pyast

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tools as T
import harness as H

W = os.environ.get('SISI_WORKDIR', os.path.dirname(HERE))
PLUG = os.path.join(HERE, '自学工具')
LOG = os.path.join(W, '知识', '学习日志.md')
REG = os.path.join(W, '升级提案.json')
os.makedirs(os.path.dirname(LOG), exist_ok=True)
os.makedirs(PLUG, exist_ok=True)


# ---------- 学习领域（主人 2026-10-29 指定要扩到这九块） ----------
DOMAINS = {
    'AI': {
        'gh': ['llm agent memory', 'agent self-improvement', 'context compression llm',
               'agent evaluation harness', 'llm as judge rubric'],
        'bili': ['AI agent 开发', '大模型 智能体 原理'],
        'web': ['大模型 Agent 最新进展'],
    },
    'IT': {
        'gh': ['linux troubleshooting tool', 'prompt caching agent', 'ffmpeg fast video pipeline',
               'python stdlib tricks', 'systemd timer patterns'],
        'bili': ['Linux 运维 入门'],
        'web': ['Linux 命令 技巧 2026'],
    },
    '数据分析': {
        'gh': ['video analytics retention', 'ab test significance python', 'data pipeline lightweight'],
        'bili': ['数据分析 入门 指标'],
        'web': ['短视频 完播率 数据分析 方法'],
    },
    '运营': {
        'gh': ['social media scheduler', 'growth experiment framework'],
        'bili': ['账号运营 冷启动', 'B站 UP主 涨粉'],
        'web': ['抖音 冷启动 流量池 机制', '小红书 笔记 起号 方法'],
    },
    '内容创作': {
        'gh': ['short video hook retention', 'storytelling micro fiction structure',
               'vertical video retention curve', 'text card motion design'],
        'bili': ['短视频 文案 写法', '故事 结构 讲法'],
        'web': ['短视频 开头 三秒 钩子 案例'],
    },
    '金融': {
        'gh': ['personal finance tracker', 'quant backtest lightweight'],
        'bili': ['经济学 入门 通俗', '理财 基础 常识'],
        'web': ['央行 降准 降息 影响 通俗解释', '普通人 理财 常识'],
    },
    '交流沟通': {
        'gh': ['conversation design chatbot'],
        'bili': ['沟通 技巧 说话', '非暴力沟通'],
        'web': ['怎么把话说清楚 沟通 技巧'],
    },
    '人文历史': {
        'gh': [],
        'bili': ['历史 故事 通俗', '人文 通识'],
        'web': ['中国历史 冷知识', '社会学 常识 普及'],
    },
    '网络热梗': {
        'gh': [],
        'bili': ['热梗 出处', '网络流行语 盘点'],
        'web': ['最近 网络热梗 出处 2026', '抖音 热门 梗 解释'],
    },
}

def pick_domain():
    """哪个领域最久没学，就学哪个（保证九块都轮得到）。"""
    d = load_learned()
    d.setdefault('domains', {})
    name = sorted(DOMAINS, key=lambda k: d['domains'].get(k, 0))[0]
    d['domains'][name] = d['domains'].get(name, 0) + 1
    save_learned(d)
    return name

QUERY_POOL = [
    'llm agent memory', 'agent self-improvement', 'prompt caching agent',
    'agent tool use benchmark', 'context compression llm',
    'short video hook retention', 'storytelling micro fiction structure',
    'vertical video retention curve', 'tts prosody natural speech',
    'video cover click through rate', 'douyin algorithm distribution',
    'bilibili recommendation mechanism', 'agent evaluation harness',
    'self rewarding agent pitfalls', 'llm as judge rubric',
    'edge tts emotion control', 'ffmpeg fast video pipeline',
    'subtitle burn in performance', 'text card motion design',
    'ai generated content disclosure policy',
]
LEARNED = os.path.join(W, '已学.json')

def load_learned():
    try:
        d = json.load(open(LEARNED, encoding='utf-8'))
        d.setdefault('refs', []); d.setdefault('hashes', []); d.setdefault('queries', {})
        d.setdefault('items', [])   # 条目级去重：同一个视频/文章不再看第二次
        return d
    except Exception:
        return {'refs': [], 'hashes': [], 'queries': {}}

def save_learned(d):
    json.dump(d, open(LEARNED, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def pick_queries(n=5):
    """挑最久没查过的 n 个查询——保证每轮看到的东西是新的。"""
    d = load_learned()
    q = sorted(QUERY_POOL, key=lambda x: d['queries'].get(x, 0))[:n]
    for x in q:
        d['queries'][x] = d['queries'].get(x, 0) + 1
    save_learned(d)
    return q

QUERIES = QUERY_POOL[:5]   # 兜底

def find_github(queries=None):
    out = []
    for q in (queries or QUERIES):
        try:
            r = T.github_search(q, kind='repositories')
            for x in (r.get('results') or [])[:3]:
                out.append({'src': 'github', 'name': x.get('name'), 'stars': x.get('stars'),
                            'desc': (x.get('desc') or '')[:160], 'why_query': q})
        except Exception as e:
            out.append({'src': 'github', 'error': str(e)[:80], 'why_query': q})
    return out

def find_bili(queries=None):
    out = []
    for q in (queries or ['AI agent 开发', '大模型 智能体 原理', 'LLM 上下文 工程']):
        try:
            r = T.bili_search(q)
            for x in (r.get('results') or [])[:2]:
                out.append({'src': 'bili', 'bvid': x.get('bvid'), 'title': x.get('title'),
                            'play': x.get('play'), 'why_query': q})
        except Exception as e:
            out.append({'src': 'bili', 'error': str(e)[:80], 'why_query': q})
    return out

def item_id(src, it):
    """一条内容 = 一个稳定 id。**按条目去重，不按标题、不按类**（主人 2026-10-29 要求）。
    github → 仓库全名；bili → BV 号；youtube → 视频 id；web → 去参网址；
    xiaohongshu → 笔记 id；x/twitter → 推文 id；reddit → 帖子 id；v2ex → 楼层 id。"""
    import re
    if src == 'github':
        return 'gh:' + (it.get('name') or '').lower()
    if src == 'bili':
        return 'bv:' + (it.get('bvid') or '')
    if src == 'youtube':
        return 'yt:' + (it.get('id') or it.get('video_id') or '')
    if src == 'xiaohongshu':
        u = it.get('url') or ''
        m = re.search(r'/(?:item|explore)/([0-9a-f]{16,})', u)
        return 'xhs:' + (m.group(1) if m else u)
    if src in ('twitter', 'x'):
        u = it.get('url') or ''
        return 'tw:' + (u.rstrip('/').split('/')[-1] if u else '')
    if src == 'reddit':
        u = it.get('url') or ''
        return 'rd:' + (u.rstrip('/').split('/comments/')[-1][:24] if 'comments' in u else u)
    if src == 'v2ex':
        u = it.get('url') or ''
        m = re.search(r'/t/(\d+)', u)
        return 'v2:' + (m.group(1) if m else u)
    u = (it.get('url') or it.get('name') or '').split('?')[0]
    return 'web:' + u

def read_material(items, limit=6):
    """把候选读成能判断的文本：GitHub 读 README，B站读字幕开头。已经学过的直接跳过。"""
    import hashlib
    d = load_learned()
    seen_items = set(d.get('items', [])); seen_h = set(d['hashes'])
    material = []
    skipped = []
    for it in items[:limit * 3]:
        try:
            if it['src'] == 'github' and it.get('name'):
                f = T.github_file(it['name'], '/README.md')
                txt = (f.get('text') or '')[:1500]
                material.append({'ref': it['name'], 'id': item_id('github', it), 'text': txt})
            elif it['src'] == 'bili' and it.get('bvid'):
                s = T.bili_subtitle(it['bvid'])
                txt = (s.get('text') or '')[:1200]
                if txt:
                    material.append({'ref': it.get('title') or it['bvid'], 'id': item_id('bili', it), 'text': txt})
        except Exception:
            continue
    # 去重：出处学过、或内容指纹学过，都不再学
    fresh = []
    for m in material:
        hh = hashlib.md5(' '.join(m['text'].split())[:800].encode()).hexdigest()[:16]
        if m.get('id') in seen_items or hh in seen_h:
            skipped.append(m['ref']); continue
        m['hash'] = hh
        fresh.append(m)
        if len(fresh) >= limit: break
    if skipped:
        print(f'跳过已学过的 {len(skipped)} 份：{", ".join(skipped[:4])}')
    return fresh

def ask_judge(material, mine, domain=''):
    body = {
        'model': 'deepseek-flash',
        'messages': [
            {'role': 'system', 'content':
             '你在帮一个住在 NAS 上的 AI 决定要不要学一样东西。只输出 JSON。\n'
             '它现在会：写一分钟竖屏字卡故事（B站/抖音/小红书发布）、读写文件、跑 shell（有 root）、'
             '看 B站数据和 GitHub、自己改自己的代码、每 6 小时进化一次规则。\n'
             '判断标准只有一条：这东西能不能让它「做出更好的内容」或「更会自己改进」。'
             '不要因为「听起来高级」就打高分。\n'
             '输出键：score(0-10 有用性)、can_use(现在就能用吗 true/false)、'
             'kind(rule/tool/pkg/none)、scope(content=直接改善作品的、meta=只管我自己怎么进化/管理、tool=新功能)、'
             'name(功能或包名)、why(一句话)、'
             'code(仅 kind=tool 时：必须严格照下面这个契约写，'
             '用一个 json 里的 "code" 字段给出完整模块代码；'
             'register(TOOLS) 必须把工具登记进传进来的 TOOLS 字典，并 return {"tools": [名字列表]}；'
             '工具函数必须能无参调用一次不崩)：\n'
             'def 某功能(x="默认"):\n    return {"ok": True, ...}\n\n'
             'def register(TOOLS):\n'
             '    TOOLS["某功能名"] = {"fn": 某功能, "desc": "一句话", '
             '"params": {"x": ("string", "说明")}, "required": []}\n'
             '    return {"tools": ["某功能名"]}\n'
             'evidence(材料里的原话或数字)'},
            {'role': 'user', 'content': f'我现在的状态：\n{mine}\n这一轮学的领域：{domain}\n\n材料：\n' +
             '\n---\n'.join(f"[{m['ref']}]\n{m['text']}" for m in material) +
             '\n\n只挑最有用的那一条给结论。没有值得学的就输出 {"score":0,"kind":"none"}。'}
        ], 'temperature': 0.2
    }
    import urllib.request
    key = open(os.environ.get('SISI_KEY_FILE', os.path.expanduser('~/.dsh/whale-work/思思/.deepseek-key')),
               encoding='utf-8').read().strip()
    req = urllib.request.Request('https://api.deepseek.com/v1/chat/completions',
                                 data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = json.loads(r.read().decode())['choices'][0]['message']['content']
    s, e = raw.index('{'), raw.rindex('}') + 1
    return json.loads(raw[s:e])

def mine_state():
    return (f'工具 {len(T.TOOLS)} 个；自己写的插件 {len(T.plugin_status()["loaded"])} 个；'
            f'规则补丁 {sum(1 for _ in open(os.path.join(HERE, "规则补丁.md"), encoding="utf-8")) if os.path.exists(os.path.join(HERE, "规则补丁.md")) else 0} 条')

def try_install_plugin(name, code):
    """把自己写的新功能落成插件文件，过语法 + 试跑 + 注册三关，过不了就删。"""
    safe = ''.join(ch for ch in name if ch.isalnum() or ch == '_')[:30] or 'tool'
    fp = os.path.join(PLUG, f'{safe}.py')
    open(fp, 'w', encoding='utf-8').write('"""自学插件：' + name + '"""\n' + code + '\n')
    try:
        pyast.parse(open(fp, encoding='utf-8').read())
    except SyntaxError as e:
        os.remove(fp)
        return {'ok': False, 'error': f'语法错：{e}'}
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location('p_' + safe, fp)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        reg = getattr(mod, 'register', None)
        if not reg:
            raise RuntimeError('没有 register()')
        got = reg({}) or {}
        names = got.get('tools') or []
        if not names:
            raise RuntimeError('register() 没返回 tools')
        fn = None
        for n in names:
            if hasattr(mod, n):
                fn = getattr(mod, n); break
        if fn is None:
            raise RuntimeError('返回的工具名找不到对应函数')
        # 试跑：无参跑一次，不准崩
        fn()
        return {'ok': True, 'file': fp, 'tools': names}
    except Exception as e:
        try: os.remove(fp)
        except Exception: pass
        return {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:120]}'}

def apply(verdict, yes=False):
    kind = verdict.get('kind')
    if kind == 'none' or (verdict.get('score') or 0) < 5:
        return '不值得学，跳过'
    if kind == 'rule':
        try:
            cur = open(os.path.join(HERE, '规则补丁.md'), encoding='utf-8').read()
        except FileNotFoundError:
            cur = ''
        n_rules = sum(1 for l in cur.splitlines() if l.startswith('- '))
        meta = sum(1 for l in cur.splitlines() if l.startswith('- ') and any(
            w in l for w in ('进化', '规则', '评测', '回测', '记忆', '轨迹')))
        name = verdict.get('name') or ''
        scope = (verdict.get('scope') or '').strip()
        # 没给 scope 就按老办法猜；给了 scope 以 scope 为准
        if not scope:
            cw = ('内容', '开场', '钩子', '字卡', '结尾', '标题', '封面', '节奏', '文案', '选题', '完播',
                  '起承转合', '结论先行', '流量池', '点击率', '留存')
            scope = 'content' if any(w in name for w in cw) else 'meta'
        if meta >= 3 and scope == 'meta':
            # 不是内容类又撞了配额：别丢掉，记进「待定提案」，等有人看
            try:
                pend = json.load(open(os.path.join(W, '待定提案.json'), encoding='utf-8'))
            except Exception:
                pend = []
            pend.append({'at': f'{datetime.datetime.now():%F %T}', 'rule': name,
                         'why': verdict.get('why'), 'evidence': verdict.get('evidence')})
            json.dump(pend, open(os.path.join(W, '待定提案.json'), 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            return f'规则补丁已有 {n_rules} 条（{meta} 条讲进化），这条不是内容类，先放进待定提案'
        key = lambda t: ''.join(ch for ch in t if ch.isalnum())
        if verdict.get('name') and (verdict['name'] in cur
                                    or (key(verdict['name']) and key(verdict['name'])[:16] in ''.join(key(l) for l in cur.splitlines()))):
            return '这条（或很像的）已经在规则补丁里了，不重复加'
        import 快照
        快照.snapshot('学习提案改规则前')
        with open(os.path.join(HERE, '规则补丁.md'), 'a', encoding='utf-8') as f:
            f.write(f"- {verdict['name']}　（学习{datetime.datetime.now():%m%d%H%M}｜{verdict.get('why','')}）\n")
        return f"规则已写入：{verdict['name']}"
    if kind == 'pkg':
        import 供应链
        return str(供应链.install(verdict['name'], '思思(自学)', verdict.get('why', '')))[:200]
    if kind == 'tool':
        if not yes:
            return '提案：写一个新功能 ' + str(verdict.get('name')) + '（没落地，加 --yes 才落）'
        return str(try_install_plugin(verdict.get('name') or 'newtool', verdict.get('code') or ''))[:250]
    return '不认识的类型：' + str(kind)

def find_web(queries):
    out = []
    for q in (queries or [])[:2]:
        try:
            r = T.web_search(q)
            for x in (r.get('hits') or [])[:2]:
                out.append({'src': 'web', 'name': x.get('title'), 'url': x.get('url'),
                            'desc': (x.get('snippet') or '')[:160]})
        except Exception as e:
            out.append({'src': 'web', 'error': str(e)[:60]})
    return out

def read_web(items, limit=3):
    """网页材料：直接抓正文前 1200 字。"""
    got = []
    for it in items[:limit]:
        if not it.get('url'): continue
        try:
            r = T.web_fetch(it['url'])
            txt = (r.get('text') or '')[:1200]
            if len(txt) > 200:
                got.append({'ref': it.get('name') or it['url'], 'text': txt})
        except Exception:
            continue
    return got

def main():
    yes = '--yes' in sys.argv
    t0 = time.time()
    domain = pick_domain()
    cfg = DOMAINS[domain]
    print(f'这轮学「{domain}」')
    gh = find_github(pick_queries(3) if cfg['gh'] else [])
    bl = find_bili(cfg['bili'])
    web = find_web(cfg['web'])
    material = read_material(gh + bl) + read_web(web)
    material = material[:6]
    print(f'查到 github {len(gh)} 条、B站 {len(bl)} 条、网页 {len(web)} 条，能读的有 {len(material)} 份')
    if not material:
        print('没读到材料，这轮不学（不瞎猜）'); return 0
    verdict = ask_judge(material, mine_state(), domain)
    print('判断：', json.dumps(verdict, ensure_ascii=False)[:400])
    result = apply(verdict, yes)
    print('落地：', result)
    rec = {'at': f'{datetime.datetime.now():%F %T}', 'domain': domain, 'verdict': verdict, 'result': result,
           'seconds': round(time.time() - t0, 1), 'materials': [m['ref'] for m in material]}
    try:
        reg = json.load(open(REG, encoding='utf-8'))
    except Exception:
        reg = []
    reg.append(rec)
    json.dump(reg, open(REG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    d = load_learned()
    for m in material:
        d['refs'].append(m['ref'])
        if m.get('id'):
            d.setdefault('items', [])
            if m['id'] not in d['items']:
                d['items'].append(m['id'])
        if m.get('hash'): d['hashes'].append(m['hash'])
    d['refs'] = d['refs'][-400:]; d['hashes'] = d['hashes'][-400:]
    d['items'] = d.get('items', [])[-2000:]   # 条目 id 记多点，别越学越回头
    save_learned(d)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"\n## {rec['at']} 自学一轮（{domain}）\n"
                f"- 材料：{', '.join(rec['materials'])}\n"
                f"- 判断：{verdict.get('score')} 分 | {verdict.get('kind')} | {verdict.get('why','')}\n"
                f"- 落地：{result}\n")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
