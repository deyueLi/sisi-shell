#!/usr/bin/env python3
"""整机自检：把每个工具、每个子系统跑一遍，记录「成 / 不成 / 为什么」。

原则：
  · 只读、或写自己的临时文件；绝不发布、绝不删别人的东西
  · 每一项都记耗时和返回码，不靠感觉说「应该没问题」
  · 结论写进 data/work/自检报告.md，同时打印一张表
用法：python3 自检.py
"""
import os, sys, json, time, traceback, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tools as T
import harness as H

W = os.environ.get('SISI_WORKDIR', '$SISI_ROOT/data/work')
TMP = os.path.join(W, '自检临时')
os.makedirs(TMP, exist_ok=True)
rows = []

def check(name, fn, need=None):
    t0 = time.time()
    try:
        r = fn()
        ok = True
        detail = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)[:160]
        if need and not need(r):
            ok = False
            detail = '返回了，但内容不对：' + detail
    except Exception as e:
        ok = False
        detail = f'{type(e).__name__}: {str(e)[:150]}'
    dt = time.time() - t0
    rows.append((name, ok, round(dt, 1), detail))
    print(('✓' if ok else '✗'), f'{name:<18}', f'{dt:5.1f}s', detail[:100].replace('\n', ' '))
    return ok

# ---------- 基础：文件 ----------
f = os.path.join(TMP, 'a.txt')
check('write_file', lambda: T.write_file(f, '自检写入\n第二行'))
check('read_file', lambda: T.read_file(f), lambda r: '自检写入' in str(r))
check('list_dir', lambda: T.list_dir(TMP), lambda r: 'a.txt' in str(r))
check('read 不存在的文件(应报错不崩)', lambda: T.read_file(os.path.join(TMP, 'nope.txt')), lambda r: '不存在' in str(r) or 'Errno' in str(r))

# ---------- 记忆 ----------
check('memory_add', lambda: T.memory_add(f'自检探针 {datetime.datetime.now():%H%M%S}',
                                          keywords=['自检', '探针'], level='fact', project='全局', importance=1))
check('memory_search', lambda: T.memory_search('自检探针'), lambda r: '探针' in str(r))

# ---------- 待办 ----------
check('todo_add', lambda: T.todo_add('自检：删掉我'))
check('todo_list', lambda: T.todo_list(), lambda r: '自检' in str(r))

# ---------- shell ----------
check('run_shell echo', lambda: T.run_shell('echo sisisi'), lambda r: 'sisisi' in str(r))
check('run_shell sudo', lambda: T.run_shell('sudo -n true && echo SUDO_OK'), lambda r: 'SUDO_OK' in str(r))

# ---------- 求知 ----------
check('web_search', lambda: T.web_search('deepseek api 价格'), lambda r: len(str(r)) > 80)
check('web_fetch', lambda: T.web_fetch('https://api.github.com/repos/bojieli/ai-agent-book'), lambda r: 'repo' in str(r).lower() or 'name' in str(r).lower())
check('learn_note', lambda: T.learn_note('自检笔记', '这是一条自检记录，不是学习内容。', 'https://example.com/zijian'))

# ---------- B站 / GitHub ----------
check('bili_view', lambda: T.bili_view('BV1Ffsf6NEot'), lambda r: '值夜班09' in str(r))
check('bili_comments', lambda: T.bili_comments('BV1iRsX6kEre'))
check('bili_search', lambda: T.bili_search('值夜班'), lambda r: len(str(r)) > 30)
check('bili_subtitle', lambda: T.bili_subtitle('BV1bW411n7fY'))
check('github_search', lambda: T.github_search('ai agent harness'), lambda r: len(str(r)) > 40)
check('github_file', lambda: T.github_file('bojieli/ai-agent-book', '/book/chapter1.md'), lambda r: len(str(r)) > 500)

# ---------- Mac 的手 ----------
check('hands_ping', lambda: T.hands_ping(), lambda r: r.get('ok'))
check('hands(phone_listen)', lambda: T.hands('phone_listen'))
check('upload_to_mac', lambda: T.upload_to_mac(f, 'zijian.txt'), lambda r: r.get('ok'))

# ---------- 供应链 ----------
check('audit_packages', lambda: T.audit_packages())

# ---------- 壳的机制 ----------
check('gate 正常命令', lambda: H.gate('run_shell', {'command': 'ls /tmp'}, T.TOOLS), lambda r: r[0] is True)
# 2026-10-30：主人给了全删权，`rm -rf /volume1` 现在是放行的（只护相册/备份/系统本身）。
# 所以这条改成测「机器本身」和「相册」两样——那才是真该拦的。
check('gate 拦删系统', lambda: H.gate('run_shell', {'command': 'rm -rf /'}, T.TOOLS), lambda r: r[0] is False)
check('gate 拦删相册', lambda: H.gate('run_shell', {'command': 'rm -rf /volume1/相册/a.jpg'}, T.TOOLS), lambda r: r[0] is False)
check('gate 放行普通删除', lambda: H.gate('run_shell', {'command': 'rm -rf /tmp/foo'}, T.TOOLS), lambda r: r[0] is True)
check('state_bar', lambda: H.state_bar(3, 30, 0.12, float('inf'), time.time() - 40))
check('need_compact', lambda: H.need_compact([{'role': 'user', 'content': 'x' * 70000}]), lambda r: r is True)
check('classify_error', lambda: H.classify_error('Connection timed out'), lambda r: r is not None)
check('repair_trajectory', lambda: H.repair_trajectory([{'role': 'assistant', 'tool_calls': [{'id': 'x', 'function': {'name': 'run_shell', 'arguments': '{}'}}]}]))
check('score_trajectory', lambda: H.score_trajectory([{'role': 'tool', 'content': 'ok'}]))
check('prompt 长度', lambda: len(H.STATIC_PREFIX), lambda r: 100 < (r if isinstance(r, int) else 0) < 6000)

# ---------- 省时 ----------
import 省时
check('省时.is_peak', lambda: 省时.label())
check('省时.next_offpeak', lambda: 省时.next_offpeak().strftime('%m-%d %H:%M'))

# ---------- 快照 / 进化 ----------
import 快照, 进化
check('快照.snapshot', lambda: 快照.snapshot('自检'), lambda r: r is not None)
check('快照.list_snaps', lambda: 快照.list_snaps(), lambda r: len(str(r)) > 2)
check('进化 提案(不应用)', lambda: 进化.propose() if hasattr(进化, 'propose') else 'skip')

# ---------- 自主 ----------
check('自主.tick 存在', lambda: hasattr(__import__('自主'), 'tick'), lambda r: r is True)

# ---------- 收尾 ----------
ok_n = sum(1 for r in rows if r[1])
bad = [r for r in rows if not r[1]]
print(f'\n合计 {len(rows)} 项：成 {ok_n}，不成 {len(bad)}')
rep = os.path.join(W, '自检报告.md')
with open(rep, 'w', encoding='utf-8') as fh:
    fh.write(f'# 自检报告 {datetime.datetime.now():%F %T}\n\n')
    fh.write(f'共 {len(rows)} 项，成 {ok_n}，不成 {len(bad)}\n\n| 项 | 结果 | 耗时 | 细节 |\n|---|---|---|---|\n')
    for n, ok, dt, d in rows:
        fh.write(f'| {n} | {"✓" if ok else "✗"} | {dt}s | {str(d)[:120].replace("|", "/")} |\n')
    if bad:
        fh.write('\n## 不成的那几项\n\n')
        for n, ok, dt, d in bad:
            fh.write(f'- **{n}**：{d}\n')
print('报告：', rep)
