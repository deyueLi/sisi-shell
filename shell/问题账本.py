#!/usr/bin/env python3
"""每晚对账的真面目：**不是对钱，是对我们俩遇到的问题。**

主人 2026-10-29 23:41 的原话：
  「对账不是对财务，是核对你们俩遇到的问题，有没有重复的，有没有被覆盖的，被冲掉的。没解决的。」

所以这个脚本只干一件事：从今天的运行日志里，把她遇到的**真问题**捞出来，写成条目。
（我这边的问题由我自己写进同一份账本，两边合起来比。）

三类判定：
  重复   同一个问题两边都踩了 —— 说明不是偶发，是系统性的
  被冲掉 她改的东西被外部覆盖（部署/回滚）—— 查快照条数
  没解决 status 还是 open 的

产出：$SISI_ROOT/data/work/日志/问题-她.jsonl（一行一条）
"""
import os, sys, json, glob, datetime, re

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get('SISI_WORKDIR', os.path.dirname(HERE))
OUT = os.path.join(W, '日志', '问题-她.jsonl')
SNAP = os.path.join(os.path.dirname(W), '进化快照')
RULE = os.path.join(HERE, '规则补丁.md')
# 对账跑在 00:05，那时候「今天」才过了 5 分钟——要算的是**刚刚结束的那一天**。
# 用法：python3 问题账本.py --day 2026-10-29
def _day():
    for i, a in enumerate(sys.argv):
        if a == '--day' and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return datetime.date.today().isoformat()


TODAY = _day()

# 哪些「被拦」不算真问题（她自己写错参数 / 重复调用被拦），哪些算
NOT_A_PROBLEM = re.compile(r'缺参数|要是整数|要是字符串|要是数组|必须是绝对路径|同一调用已重复|原地打转|连败')
REAL_RISK = re.compile(r'破坏性|敏感|提权|rm -rf|关机|格式化')


def norm(s):
    """把错误文本压成可比较的样子：去掉具体路径/ID/数字，只留骨架。"""
    s = re.sub(r'\[[^\]]*\]', '', str(s))
    s = re.sub(r"'[^']{0,60}'", "'X'", s)
    s = re.sub(r'\b\d{2,}\b', 'N', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:90]


def mine(day=TODAY):
    f = os.path.join(HERE, 'logs', day + '.jsonl')
    out = {}
    if not os.path.exists(f):
        return []
    for ln in open(f, encoding='utf-8'):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        tool = r.get('tool')
        if not tool:
            continue
        if r.get('blocked'):
            txt = str(r.get('blocked'))
            if NOT_A_PROBLEM.search(txt):
                kind = '自己的参数写错（被闸门拦下）'
            elif REAL_RISK.search(txt):
                kind = '真的危险操作（该拦）'
            else:
                kind = '被闸门拦下'
            key = 'blocked|' + tool + '|' + norm(txt)
            out.setdefault(key, {'at': TODAY, 'side': '她', 'tool': tool, 'kind': kind,
                                 'problem': f"{tool}：{txt[:80]}", 'hit': 0, 'tag': '被拦'})
            out[key]['hit'] += 1
        elif r.get('error'):
            txt = str(r.get('error'))
            key = 'error|' + tool + '|' + norm(txt)
            out.setdefault(key, {'at': TODAY, 'side': '她', 'tool': tool, 'kind': '调用出错',
                                 'problem': f"{tool}：{txt[:80]}", 'hit': 0, 'tag': '出错'})
            out[key]['hit'] += 1
    return list(out.values())


def clobbered():
    """她的规则到底有没有被外部覆盖：拿现在条数跟历史上最多的一次比。"""
    try:
        now = sum(1 for l in open(RULE, encoding='utf-8') if l.strip().startswith('- '))
    except FileNotFoundError:
        return None
    best = now
    for d in glob.glob(os.path.join(SNAP, '*')):
        p = os.path.join(d, '规则补丁.md')
        if not os.path.exists(p):
            continue
        try:
            n = sum(1 for l in open(p, encoding='utf-8') if l.strip().startswith('- '))
            best = max(best, n)
        except Exception:
            continue
    if best > now:
        return {'at': TODAY, 'side': '她', 'tool': '规则补丁.md', 'kind': '被冲掉',
                'problem': f'现在 {now} 条，历史上最多时有 {best} 条 —— 可能被部署/回滚覆盖',
                'hit': best - now, 'tag': '覆盖'}
    return None


def main():
    items = mine()
    cb = clobbered()
    if cb:
        items.append(cb)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        for it in sorted(items, key=lambda x: -x['hit']):
            f.write(json.dumps(it, ensure_ascii=False) + '\n')
    print(f'{OUT}｜{len(items)} 条')
    for it in sorted(items, key=lambda x: -x['hit'])[:8]:
        print(f"  [{it['hit']}次] {it['kind']}：{it['problem'][:60]}")
    if cb:
        print('  ⚠️ 规则条数比历史少：', cb['problem'])


if __name__ == '__main__':
    main()
