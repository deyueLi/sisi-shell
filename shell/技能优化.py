#!/usr/bin/env python3
"""技能优化：照 microsoft/SkillOpt 那套，把「规则补丁.md」当可训练参数来练。

和 进化.py 的区别（进化.py 是只会 append 的雏形）：
  · 编辑是有界的 add / delete / replace，不是只会加
  · 收不收，看「留出门」——拿几条没参与挖矿的轨迹做成对判断
  · 被拒的编辑进缓冲，别反复提同一个馊主意
  · 产物长度卡在 300~2000 字（超过就强制压缩）
  · 改之前快照，改完自检，随时能回滚

用法：
  python3 技能优化.py propose      # 只提编辑，不动文件
  python3 技能优化.py run          # 提 + 过门 + 落地
  python3 技能优化.py run --yes    # 无人值守（门还是照样过）
  python3 技能优化.py reject       # 看被拒缓冲
"""
import os, sys, json, glob, datetime, random, re, hashlib, inspect

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H
import 快照 as SNAP
import 进化 as EVO   # 复用它的 call() 和登记表

PATCH = os.path.join(HERE, '规则补丁.md')
LOGDIR = os.path.join(HERE, 'logs')
REJECT = os.path.join(HERE, '技能优化-被拒.json')
MAX_EDITS = 3          # 一轮最多改几条（文本学习率）
MAX_CHARS = 2000       # 产物上限
MIN_CHARS = 300        # 产物下限
HOLDOUT_N = 4          # 留出门留几次运行
MIN_HOLD = 6           # 留出门少于这么多条记录就不练（证据不足宁可不动）
SEAL_DIR = os.path.join(os.path.dirname(HERE), 'data', 'work', '进化-封存')
SEAL_STATE = os.path.join(HERE, '进化-封存状态.json')
K_CONFIRM = 3          # 过门后要 K 次独立确认（Raven 的 K=3）

# 失败原因类别（照 Raven 的 WHY：一轮只打 1-2 类，别打散弹）
WHY_TAXONOMY = ['没验就收工', '路径/参数写错', '同一件事反复试', '工具选错',
                '误判已有结果', '上下文太长开始忘事', '其它']

# 哪些「失败」不该算到这版规则的账上（基础设施的锅）
INFRA = re.compile(r'超时|timeout|timed out|429|502|503|504|Connection|URLError|'
                   r'RateLimit|余额不足|insufficient|context_length|连接错误', re.I)


def load_reject():
    try:
        return json.load(open(REJECT, encoding='utf-8'))
    except Exception:
        return []


def save_reject(x):
    json.dump(x[-40:], open(REJECT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def patch_text():
    try:
        return open(PATCH, encoding='utf-8').read().strip()
    except FileNotFoundError:
        return ''


def todays_records(day=None):
    day = day or datetime.date.today().isoformat()
    return H.read_log(os.path.join(LOGDIR, day + '.jsonl'))


def digest_of(recs, limit=2500):
    lines = []
    for r in recs:
        if not ('tool' in r or 'blocked' in r or 'event' in r):
            continue
        bits = [str(r.get(k, '')) for k in ('step', 'tool', 'event', 'blocked', 'error', 'say')]
        lines.append(' '.join(b for b in bits if b and b != 'None'))
    return '\n'.join(lines)[-limit:]


def all_records():
    """把几天的日志全读进来，按时间排。"""
    out = []
    for f in sorted(glob.glob(os.path.join(LOGDIR, '20*.jsonl'))):
        day = os.path.basename(f)[:10]
        for r in H.read_log(f):
            r['_day'] = day
            out.append(r)
    return out


def split_runs(recs):
    """按「一次运行」切段：出现 goal，或者 step 从 1 重新开始，就算新的一次。"""
    runs, cur, last_step = [], [], None
    for r in recs:
        st = r.get('step')
        if (r.get('goal') is not None or (st == 1 and last_step not in (None, 0) and last_step > 1)) and cur:
            runs.append(cur); cur = []
        cur.append(r)
        if st is not None:
            last_step = st
    if cur:
        runs.append(cur)
    return runs


def is_infra(rec):
    """这条失败是不是「基础设施的锅」——超时、429/5xx、余额不足、连接断。
    这类不算规则变差（Raven 的 Gate-f）：不剔掉的话，一次断网就能让结论反转。"""
    if rec.get('timed_out'):
        return True
    txt = ' '.join(str(rec.get(k) or '') for k in ('error', 'blocked', 'result'))
    return bool(INFRA.search(txt))


def mine_usable(recs):
    """返回 (可用于挖矿的记录, 剔掉的基础设施失败条数)。"""
    keep, dropped = [], 0
    for r in recs:
        if is_infra(r):
            dropped += 1
            continue
        keep.append(r)
    return keep, dropped


def config_fingerprint():
    """把「影响可比性」的配置拍成一个指纹。配置变了就不该拿新旧结果比。
    （Raven：a run refuses to resume under a changed configuration）"""
    cfg = {}
    try:
        cfg = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
    except Exception:
        pass
    parts = [str(cfg.get('model')), str(cfg.get('max_steps')),
             str(cfg.get('provider')), str(len(H.STATIC_PREFIX))]
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]


def measure_hash():
    """打分与评审逻辑的指纹。它变了，说明「量尺」被人动过，旧结论不算数。"""
    src = ''
    try:
        src += inspect.getsource(judge)
    except Exception:
        pass
    try:
        src += inspect.getsource(H.score_trajectory)
    except Exception:
        pass
    return hashlib.sha256(src.encode()).hexdigest()[:16]


def split_sets(recs):
    """挖矿集 vs 留出门：**留出最后几次运行**，挖矿时看不到它们。
    数据太少时退化为「按步切」：留最后一步，其余挖矿。"""
    runs = [r for r in split_runs(recs) if any(x.get('step') for x in r)]
    if len(runs) >= 2:
        k = max(1, min(HOLDOUT_N // 2 or 1, len(runs) - 1))
        hold = [x for run in runs[-k:] for x in run]
        mine = [x for run in runs[:-k] for x in run]
        return mine, hold
    # 只有一次运行 → 按步切
    steps = {}
    for r in recs:
        if r.get('step') is None:
            continue
        steps.setdefault(r['step'], []).append(r)
    keys = sorted(steps)
    if len(keys) < 2:
        return recs, []
    hold = steps[keys[-1]]
    mine = [r for k in keys[:-1] for r in steps[k]]
    return mine, hold


def seal_records(recs):
    """把一部分运行封存起来：内容写到单独目录，挖矿和评审都看不见。

    照 Raven 的 sealed test：test 分区「the test split is scored but stored where
    no decision step can read it; opened once, at the end」。
    我原来的毛病是「分数用的数据就是我看得见的那些」——等于边看答案边改卷子。

    返回 (可用的记录, 封存信息 or None)。每次运行的第 5 条留下来封存。
    """
    runs = [r for r in split_runs(recs) if any(x.get('step') for x in r)]
    if len(runs) < 5:
        return recs, None
    sealed_runs = [run for i, run in enumerate(runs) if i % 5 == 4]
    keep_runs = [run for i, run in enumerate(runs) if i % 5 != 4]
    if not sealed_runs:
        return recs, None
    sealed = [x for run in sealed_runs for x in run]
    keep = [x for run in keep_runs for x in run]
    try:
        os.makedirs(SEAL_DIR, exist_ok=True)
        sid = datetime.datetime.now().strftime('%m%d%H%M%S')
        path = os.path.join(SEAL_DIR, f'{sid}.jsonl')
        with open(path, 'w', encoding='utf-8') as f:
            for r in sealed:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        sha = hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]
        return keep, {'id': sid, 'path': path, 'count': len(sealed), 'sha': sha,
                      'runs': len(sealed_runs)}
    except Exception as ex:
        return recs, {'error': f'{type(ex).__name__}: {ex}'}


def sealed_state():
    try:
        return json.load(open(SEAL_STATE, encoding='utf-8'))
    except Exception:
        return {}


def open_sealed_once(sid=None):
    """开封：只许一次。开封后这一批就不能再当「没看过的测试集」用了。"""
    st = sealed_state()
    opened = st.get('opened') or {}
    files = sorted(glob.glob(os.path.join(SEAL_DIR, '*.jsonl')))
    if not files:
        return None, '没有封存集'
    path = files[-1]
    name = os.path.basename(path).replace('.jsonl', '')
    if name in opened:
        return None, f'这一批已经开封过（{opened[name]}），不能再当测试集用'
    st.setdefault('opened', {})[name] = datetime.datetime.now().isoformat(timespec='seconds')
    json.dump(st, open(SEAL_STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    recs = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
    return recs, f'开封 {name}（{len(recs)} 条）'


def propose_edits(recs, hold, whys=None):
    """让优化器模型产出有界编辑。只输出 JSON。"""
    cur = patch_text()
    rejected = [x.get('text', '')[:80] for x in load_reject()[-5:]]
    sc = H.score_trajectory(recs)
    digest = digest_of(recs)
    sys_p = ('你是技能文档的优化器。目标模型是冻结的，你只能改那份 markdown。'
             '只输出 JSON，不要解释。格式：{"edits":[{"op":"add|delete|replace",'
             '"target":"要删/要改的原文片段（op=add 时留空）","text":"新增或替换后的文本"}],'
             '"why":"一句话说明依据"}。'
             f'一轮最多 {MAX_EDITS} 条编辑；每条 text 不超过 120 字；不许多写解释。'
             '规矩要具体、可执行、能被后面的轨迹验证；不要写「要更好」这种空话。')
    user = (f'当前技能文档（{len(cur)} 字）：\n{cur or "（空）"}\n\n'
            + (('这一轮要解决的问题（先归因，别打散弹）：\n' +
                '\n'.join(f'- {w.get("class")}：{w.get("evidence","")[:80]}' for w in whys) + '\n')
               if whys else '')
            + f'一次真实运行的轨迹，得分 {sc}：\n{digest}\n'
            f'留出门里还有 {len(hold)} 条运行记录，你看不到内容，只知道存在。\n'
            + (f'之前被拒过的编辑（别再提）：\n' + '\n'.join(rejected) + '\n' if rejected else '')
            + '\n请给出能让下一次运行更省步、更少绕路的编辑。没有值得改的就输出 {"edits":[]}。')
    raw = EVO.call(sys_p, user)
    try:
        s = raw.index('{'); e = raw.rindex('}') + 1
        return json.loads(raw[s:e])
    except Exception:
        print('模型没给干净 JSON：', raw[:200])
        return {'edits': []}


def classify_why(mine, k=2):
    """先给失败归因，再谈改什么。一轮只打 1-2 类（照 Raven 的 WHY）。

    不这么做的毛病我今晚就犯了：想到哪儿改哪儿，等于打散弹。
    """
    digest = digest_of(mine, 2000)
    sys_p = ('你是失败归因器。看一段 agent 的运行轨迹，判断最该被解决的失败类型。'
             f'只能从这些类别里选：{WHY_TAXONOMY}。'
             f'只输出 JSON：{{"whys":[{{"class":"类别","evidence":"轨迹里的依据一句话"}}]}}，'
             f'最多 {k} 类，按重要性排序。')
    try:
        raw = EVO.call(sys_p, f'轨迹：\n{digest}')
        a = raw.index('{'); b = raw.rindex('}') + 1
        d = json.loads(raw[a:b])
        whys = [w for w in (d.get('whys') or []) if w.get('class') in WHY_TAXONOMY][:k]
        return whys
    except Exception:
        return []


def apply_edits(text, edits):
    """把编辑落到文本上。有界：最多 MAX_EDITS 条，结果长度受控。"""
    out = text
    done = []
    for e in edits[:MAX_EDITS]:
        op = e.get('op')
        tgt = (e.get('target') or '').strip()
        new = (e.get('text') or '').strip()
        if op == 'add' and new:
            out = (out.rstrip() + '\n- ' + new + '\n').strip()
            done.append(('add', new[:40]))
        elif op == 'delete' and tgt and tgt in out:
            out = out.replace(tgt, '', 1)
            done.append(('delete', tgt[:40]))
        elif op == 'replace' and tgt and tgt in out and new:
            out = out.replace(tgt, new, 1)
            done.append(('replace', tgt[:30]))
        else:
            continue
    # 长度约束：超了就砍最长的几条（等于强制压缩）
    while len(out) > MAX_CHARS:
        lines = [l for l in out.splitlines() if l.strip()]
        if len(lines) <= 3:
            break
        longest = max(range(len(lines)), key=lambda i: len(lines[i]))
        lines.pop(longest)
        out = '\n'.join(lines)
    return out.strip(), done


def judge(old, new, hold):
    """留出门：成对判断，新版本必须严格更好才收。"""
    if not hold:
        return False, '没有留出门，按规矩不收'
    if len(hold) < MIN_HOLD:
        return False, f'留出门只有 {len(hold)} 条（要求 ≥{MIN_HOLD}），证据不足，宁可不动'
    hd = digest_of(hold, 1200)
    sys_p = ('你是评审。给你一份 agent 的技能文档的两个版本，和几条【没参与优化】的运行轨迹。'
             '判断哪一版更可能让这些运行更少绕路、更少错误。只输出 JSON：'
             '{"pick":"A|B|tie","why":"一句话"}。A 是旧版，B 是新版。')
    user = (f'A（旧）：\n{old or "（空）"}\n\nB（新）：\n{new}\n\n'
            f'留出门里的运行轨迹：\n{hd}\n\n哪一版更可能跑得好？')
    try:
        raw = EVO.call(sys_p, user)
        s = raw.index('{'); e = raw.rindex('}') + 1
        d = json.loads(raw[s:e])
    except Exception as ex:
        return False, f'评审失败：{type(ex).__name__}'
    pick = (d.get('pick') or '').upper()
    return pick == 'B', f"评审选 {pick}｜{d.get('why','')[:60]}"


def judge_k(old, new, hold, k=K_CONFIRM):
    """K 漏斗：先用一次便宜判断粗筛，过了再 K 次独立确认，多数票才算过。

    照 Raven：cheap screen (K=1) before the expensive confirmation (K=3)。
    为什么要有：单次 LLM 判断抖得厉害，一次「选 B」可能是运气。
    """
    ok1, why1 = judge(old, new, hold)
    if not ok1:
        return False, f'K=1 粗筛没过｜{why1}', {'pass1': False}
    votes, reasons = 1, [why1]
    for i in range(k - 1):
        ok, why = judge(old, new, hold)
        votes += 1 if ok else 0
        reasons.append(why)
    passed = votes >= 2 and votes >= (k // 2 + 1)
    return passed, (f'{votes}/{k} 票｜' + '；'.join(r[:40] for r in reasons)), {'votes': votes, 'k': k}


def register(old, new, edits, why, judged, sealed=None):
    reg = EVO.load_reg()
    reg.append({'id': datetime.datetime.now().strftime('%m%d%H%M%S'),
                'kind': 'skill-edit', 'ops': [op for op, _ in edits],
                'chars_before': len(old), 'chars_after': len(new),
                'why': why[:200], 'judge': str(judged)[:300],
                'status': '待验证', 'source': 'SkillOpt-lite',
                'config_fp': config_fingerprint(),
                'measure_fp': measure_hash(),
                'sealed': sealed,
                'applied_at': datetime.datetime.now().isoformat(timespec='seconds')})
    EVO.save_reg(reg)


def run(auto=False):
    """一轮练功：剔基础设施失败 → 封存测试集 → 切留出门 → 归因 → 提案 → K 漏斗过门 → 落地。"""
    recs = all_records()
    if not recs:
        print('没有历史轨迹，不练'); return
    recs, infra_dropped = mine_usable(recs)
    if infra_dropped:
        print(f'Gate-f：剔掉 {infra_dropped} 条基础设施失败（超时/5xx/余额），它们不算规则的账')
    keep, sealed = seal_records(recs)
    if sealed and not sealed.get('error'):
        print(f"封存测试集：{sealed['count']} 条（{sealed['runs']} 次运行），"
              f"挖矿看不见，等 verify 才开封｜sha {sealed['sha']}")
    mine, hold = split_sets(keep)
    print(f'轨迹 {len(recs)} 条｜挖矿 {len(mine)}｜留出门 {len(hold)}')
    whys = classify_why(mine)
    if whys:
        print('归因：', '｜'.join(f"{w['class']}" for w in whys))
    d = propose_edits(mine, hold, whys)
    edits = d.get('edits') or []
    if not edits:
        print('没有值得改的编辑'); return
    cur = patch_text()
    new, done = apply_edits(cur, edits)
    if not done or new == cur:
        print('编辑没有真正落地（原文里找不到 target？）：', edits); return
    print('候选编辑：', done)
    ok, why, detail = judge_k(cur, new, hold)
    print('过门：', ok, '｜', why)
    if not ok:
        rj = load_reject()
        for op, txt in done:
            rj.append({'at': datetime.datetime.now().isoformat(timespec='seconds'),
                       'op': op, 'text': txt, 'judge': why[:120]})
        save_reject(rj)
        print('被拒，已进缓冲（下次挖矿会当作负面示例）')
        return
    if not auto and '--yes' not in sys.argv:
        print('过门了。要落地就加 --yes 再跑一次（或直接用 run --yes）')
        print('--- 新版预览 ---')
        print(new[:1200])
        return
    SNAP.snapshot("技能优化")
    open(PATCH, 'w', encoding='utf-8').write(new + '\n')
    register(cur, new, done, d.get('why', ''), why, sealed)
    print(f'已落地：{len(cur)} → {len(new)} 字。验证走 进化.py verify。')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'propose'
    if cmd == 'reject':
        rj = load_reject()
        print(f'被拒 {len(rj)} 条')
        for x in rj[-8:]:
            print(' ', x.get('at'), x.get('op'), (x.get('text') or '')[:50], '←', (x.get('judge') or '')[:40])
        return
    if cmd == 'propose':
        recs = todays_records()
        recs, dropped = mine_usable(recs)
        if dropped:
            print(f'Gate-f：剔掉 {dropped} 条基础设施失败')
        keep, sealed = seal_records(recs)
        if sealed and not sealed.get('error'):
            print(f"封存：{sealed['count']} 条 / {sealed['runs']} 次运行（挖矿看不见）")
        mine, hold = split_sets(keep)
        whys = classify_why(mine)
        if whys:
            print('归因：', '、'.join(w['class'] for w in whys))
        print(json.dumps(propose_edits(mine, hold, whys), ensure_ascii=False, indent=1)[:1500])
        return
    run()


if __name__ == '__main__':
    main()
