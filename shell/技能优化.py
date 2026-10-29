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
import os, sys, json, glob, datetime, random

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


def propose_edits(recs, hold):
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
            f'一次真实运行的轨迹，得分 {sc}：\n{digest}\n'
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


def register(old, new, edits, why, judged):
    reg = EVO.load_reg()
    reg.append({'id': datetime.datetime.now().strftime('%m%d%H%M%S'),
                'kind': 'skill-edit', 'ops': [op for op, _ in edits],
                'chars_before': len(old), 'chars_after': len(new),
                'why': why[:200], 'judge': judged,
                'status': '待验证', 'source': 'SkillOpt-lite',
                'applied_at': datetime.datetime.now().isoformat(timespec='seconds')})
    EVO.save_reg(reg)


def run(auto=False):
    recs = all_records()
    if not recs:
        print('没有历史轨迹，不练'); return
    mine, hold = split_sets(recs)
    print(f'轨迹 {len(recs)} 条｜挖矿 {len(mine)}｜留出门 {len(hold)}')
    d = propose_edits(mine, hold)
    edits = d.get('edits') or []
    if not edits:
        print('没有值得改的编辑'); return
    cur = patch_text()
    new, done = apply_edits(cur, edits)
    if not done or new == cur:
        print('编辑没有真正落地（原文里找不到 target？）：', edits); return
    print('候选编辑：', done)
    ok, why = judge(cur, new, hold)
    print('留出门判定：', ok, '｜', why)
    if not ok:
        rj = load_reject()
        for op, txt in done:
            rj.append({'at': datetime.datetime.now().isoformat(timespec='seconds'),
                       'op': op, 'text': txt, 'judge': why})
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
    register(cur, new, done, d.get('why', ''), why)
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
        mine, hold = split_sets(recs)
        print(json.dumps(propose_edits(mine, hold), ensure_ascii=False, indent=1)[:1500])
        return
    run()


if __name__ == '__main__':
    main()
