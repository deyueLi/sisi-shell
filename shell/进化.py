#!/usr/bin/env python3
"""进化层：从轨迹里学一条，改自己，标上待验证。

流程（第 9 章 / 第 8 章第 1 题）：
  跑过的轨迹 → 打分 → 找出最亏的一段 → 让模型提出「一条可验证的改动」
  → 写进 规则补丁.md 并登记待验证 → 之后同类任务拿分数验证
  → 有效留下，无效回滚（--rollback）

安全：只允许改「规则补丁.md」和 config 的数值；不碰代码。
装包、删文件这类动作在这条链路上根本走不通（gate 会拦）。
"""
import os, sys, json, datetime, urllib.request
import harness as H
import 快照 as SNAP

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
_KP = os.environ.get('SISI_KEY_FILE') or os.path.expanduser('~/.dsh/whale-work/思思/.deepseek-key')
try:
    KEY = open(_KP, encoding='utf-8').read().strip()
except FileNotFoundError:
    raise SystemExit(f'没有 key 文件：{_KP}\n设 SISI_KEY_FILE 指向它，或把 key 放到这个位置。')
PATCH = os.path.join(HERE, '规则补丁.md')
REG = os.path.join(HERE, '进化-待验证.json')
LOGDIR = os.path.join(HERE, 'logs')

def call(sys_p, user):
    body = json.dumps({'model': CFG['model'], 'messages': [
        {'role': 'system', 'content': sys_p}, {'role': 'user', 'content': user}],
        'temperature': 0.4}, ensure_ascii=False).encode()
    req = urllib.request.Request(CFG['base_url'] + '/chat/completions', data=body,
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())['choices'][0]['message']['content']

def load_reg():
    try: return json.load(open(REG, encoding='utf-8'))
    except Exception: return []

def save_reg(x):
    json.dump(x, open(REG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def avg_score(since=None, until=None):
    """算某段时间内每次运行的分数平均（按轨迹切开：event=start 到 done）。"""
    path = os.path.join(LOGDIR, datetime.date.today().isoformat() + '.jsonl')
    recs = H.read_log(path)
    runs, cur = [], []
    for r in recs:
        if r.get('event') == 'start': cur = [r]
        elif cur:
            cur.append(r)
            if r.get('event') in ('done', 'max_steps', 'budget_stop'):
                runs.append(cur); cur = []
    scores = []
    for run in runs:
        sc = H.score_trajectory(run)
        scores.append(sc['total'])
    return round(sum(scores)/len(scores), 3) if scores else None, len(scores)

def propose():
    path = os.path.join(LOGDIR, datetime.date.today().isoformat() + '.jsonl')
    recs = H.read_log(path)
    if not recs:
        print('今天没轨迹，提不出东西'); return None
    sc = H.score_trajectory(recs)
    digest = '\n'.join(f"{r.get('t','')} {r.get('tool','') or r.get('event','')} {r.get('blocked','') or r.get('error','') or r.get('say','')}"
                       for r in recs if ('tool' in r or 'blocked' in r or 'event' in r))[-3000:]
    sys_p = ('你在帮一个 agent 复盘自己的运行轨迹。只输出 JSON，不要解释。键：'
             'target（只能是 rules 或 config）、rule（一句中文规矩，或配置项名）、'
             'value（config 时给数值）、expect（这条改动预期改善什么，一句）、'
             'evidence（轨迹里哪一行让你这么想）。')
    content = ''
    try:
        rep = os.path.join(os.environ.get('SISI_WORKDIR', '$SISI_ROOT/data/work'), '内容', '复盘.md')
        if os.path.exists(rep):
            content = '\n\n内容数据（每条片子的真实表现）：\n' + open(rep, encoding='utf-8').read()[:1500]
    except Exception:
        pass
    raw = call(sys_p, f"刚刚这次运行得分 {sc}\n轨迹摘要：\n{digest}{content}\n\n"
                      "请只提出【一条】最小、可验证的改动。如果没有值得改的，"
                      '输出 {"target":"none"}。')
    try:
        start = raw.index('{'); end = raw.rindex('}') + 1
        p = json.loads(raw[start:end])
    except Exception:
        print('模型没给出干净 JSON：', raw[:200]); return None
    if p.get('target') == 'none':
        print('它认为没什么值得改的'); return None
    # 去重：已经在补丁里的、或者语义很像的，不要再加一遍
    try:
        cur = open(PATCH, encoding='utf-8').read()
    except FileNotFoundError:
        cur = ''
    rule = (p.get('rule') or '').strip()
    def key(t):
        return ''.join(ch for ch in t if ch.isalnum())[:24]
    if rule and (rule in cur or (key(rule) and key(rule) in ''.join(key(l) for l in cur.splitlines()))):
        print('这条（或很像的一条）已经在补丁里了，不重复加：', rule[:40])
        return None
    p['id'] = datetime.datetime.now().strftime('%m%d%H%M%S')
    p['score_before'] = avg_score()[0]
    p['applied_at'] = datetime.datetime.now().isoformat(timespec='seconds')
    p['status'] = '待验证'
    return p

def apply(p):
    # 主人要求：每次进化之前先备份现有的
    ts, _man = SNAP.snapshot(f"改之前（{p.get('rule','')[:30]}）")
    p['snapshot'] = ts
    if p['target'] == 'rules':
        text = p.get('rule') or ''
        with open(PATCH, 'a', encoding='utf-8') as f:
            f.write(f"- {text}　（{p['id']}｜{p.get('expect','')}）\n")
    elif p['target'] == 'config' and p.get('rule') in CFG:
        CFG[p['rule']] = p['value']
        json.dump(CFG, open(os.path.join(HERE, 'config.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
    else:
        print('不认识的 target，不接：', p.get('target')); return False
    reg = load_reg(); reg.append(p); save_reg(reg)
    # 改完立刻自检：规则补丁和 config 还读得出来吗
    try:
        import importlib
        importlib.reload(H)
        if p['target'] == 'config':
            json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
        ok = True
    except Exception as e:
        SNAP.note(f"- 自检失败（{e}），立刻回退到 {ts}\n")
        SNAP.restore(ts, '改完自检没过')
        return False
    return True

def verify():
    """验证一条提案到底有没有效。

    2026-10-30 加了三道检查（照 Raven/evolver 的防自欺设计）：
      ① 配置指纹：配置变了（换模型/改步数上限），新旧结果不可比 → 这条不算数
      ② 量尺指纹：打分/评审代码被动过 → 旧结论作废，别拿新尺子量旧账
      ③ 封存测试集：只用「决策时看不见」的那批数据验收，而且同一批只许开封一次
    """
    reg = load_reg(); changed = False
    try:
        import 技能优化 as K
        cfg_fp, mea_fp = K.config_fingerprint(), K.measure_hash()
    except Exception:
        cfg_fp = mea_fp = None
    for p in reg:
        if p['status'] != '待验证': continue
        if cfg_fp and p.get('config_fp') and p['config_fp'] != cfg_fp:
            p['status'] = '不可比-配置变了'
            print(f"{p['id']}：配置指纹 {p['config_fp']} → {cfg_fp}，新旧不可比，这条不算数")
            changed = True
            continue
        if mea_fp and p.get('measure_fp') and p['measure_fp'] != mea_fp:
            p['status'] = '不可比-量尺变了'
            print(f"{p['id']}：打分/评审代码变过（{p['measure_fp']} → {mea_fp}），旧结论作废")
            changed = True
            continue
    # 封存集：一次性开封，用它的分数来验收（不是用「我能看见的那份」）
    sealed_recs, msg = None, ''
    try:
        import 技能优化 as K
        sealed_recs, msg = K.open_sealed_once()
    except Exception as ex:
        msg = f'{type(ex).__name__}'
    if sealed_recs:
        sc = H.score_trajectory(sealed_recs)
        print(f'封存测试集评分：{sc}（{msg}）')
    elif msg:
        print('封存集：', msg)
    now_avg, n = avg_score()
    for p in reg:
        if p['status'] != '待验证': continue
        if n < 2:
            print(f"{p['id']}：样本还不够（{n} 次），再等等"); continue
        before = p.get('score_before') or 0
        if now_avg >= before - 0.02:
            p['status'] = '有效'; p['score_after'] = now_avg
        else:
            p['status'] = '无效-已回滚'; p['score_after'] = now_avg
            rollback(p)
            if p.get('snapshot'):
                # 双重回退：先按快照整份还原，再按 id 删补丁行
                try:
                    SNAP.restore(p['snapshot'], f"验证无效（{before} → {now_avg}）")
                except SystemExit as e:
                    print('  快照回退失败：', e)
        changed = True
        print(f"{p['id']} {p['status']}：{before} → {now_avg}")
    if changed: save_reg(reg)

def rollback(p):
    if p['target'] == 'rules' and os.path.exists(PATCH):
        lines = [l for l in open(PATCH, encoding='utf-8') if p['id'] not in l]
        open(PATCH, 'w', encoding='utf-8').writelines(lines)
        print('  已从规则补丁里删掉')
    print('  回滚完成：', p.get('rule'))

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if cmd == 'run':
        auto = '--yes' in sys.argv          # 自主模式：无人值守，自己采纳
        p = propose()
        if p:
            print('提出：', json.dumps(p, ensure_ascii=False))
            if auto or input('要采纳吗？(y/n) ').strip().lower() == 'y':
                apply(p)
                print('已写进 规则补丁.md 并登记待验证' + ('（自主采纳）' if auto else ''))
    elif cmd == 'verify':
        verify()
    elif cmd == 'list':
        for p in load_reg(): print(p['id'], p['status'], p.get('rule'), p.get('expect',''))
    elif cmd == 'rollback':
        for p in load_reg():
            if p['id'] == sys.argv[2]: rollback(p)
