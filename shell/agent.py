#!/usr/bin/env python3
"""思思壳 v0.2 —— 带 Harness 的 agent 循环。

和 v0.1 的差别（全部来自《深入理解 AI Agent》第 1、2 章）：
  1. 静态前缀单独抽出来，永不改动（KV Cache）
  2. 时间/步数/花费放轨迹末尾的状态栏，不塞系统提示
  3. 工具调用前先 validate（危险命令、非绝对路径、发布类动作都拦）
  4. 接近预算时成批压缩旧工具输出，保留最近的
  5. 同一工具连败两次，往轨迹里塞一句"换方法"
  6. 全程写日志，每一步可回放
"""
import os, sys, json, time, datetime, urllib.request
import tools as T
import harness as H

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, 'config.json'), encoding='utf-8'))
if os.environ.get('SISI_WORKDIR'): CFG['workdir'] = os.environ['SISI_WORKDIR']
_KEYPATH = os.environ.get('SISI_KEY_FILE') or os.path.expanduser('~/.dsh/whale-work/思思/.deepseek-key')
KEY = open(_KEYPATH, encoding='utf-8').read().strip()
LOG = os.path.join(HERE, 'logs', datetime.date.today().isoformat() + '.jsonl')
SPEND = os.path.join(HERE, 'logs', 'spend.json')

def log(rec):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)   # 目录不在就自己建（NAS 上第一次就是这么挂的）
    rec['t'] = datetime.datetime.now().strftime('%H:%M:%S')
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')

def spent_today():
    try: return json.load(open(SPEND, encoding='utf-8')).get(datetime.date.today().isoformat(), 0.0)
    except Exception: return 0.0

def add_spend(cny):
    try: d = json.load(open(SPEND, encoding='utf-8'))
    except Exception: d = {}
    k = datetime.date.today().isoformat()
    d[k] = round(d.get(k, 0.0) + cny, 6)
    json.dump(d, open(SPEND, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def call(messages, tools_schema):
    body = json.dumps({'model': CFG['model'], 'messages': messages, 'tools': tools_schema,
                       'tool_choice': 'auto', 'temperature': 0.6}, ensure_ascii=False).encode()
    req = urllib.request.Request(CFG['base_url'] + '/chat/completions', data=body,
                                 headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())

def cost(u):
    if not u: return 0.0
    return (u.get('prompt_tokens', 0) * CFG['price_in_per_m'] +
            u.get('completion_tokens', 0) * CFG['price_out_per_m']) / 1_000_000

def summarize(text, n=200):
    s = ' '.join(str(text).split())
    return s[:n] + ('…' if len(s) > n else '')

def run(goal, quiet=False):
    started = time.time()
    H.breaker_reset()
    schema = T.schema_list()                      # 工具定义：静态，不许变
    traj = [{'role': 'user', 'content': goal}]    # 轨迹：只往后加
    total = 0.0
    fail_streak = {}
    log({'event': 'start', 'goal': goal})

    BUDGET = CFG.get('daily_budget_cny') or float('inf')   # 0/不填 = 不限（主人 2026-10-29 取消每日上限）
    for step in range(1, CFG['max_steps'] + 1):
        if spent_today() + total >= BUDGET:
            log({'event': 'budget_stop', 'spent': round(spent_today() + total, 4)})
            return f'今天的钱用完了（{spent_today()+total:.2f} 元），停。'

        # 压缩：只在接近预算时动旧工具输出
        # 注意（OpenHands #2034 修的那类坑）：如果挑不出可压的条目，光「什么都不做」会让上下文
        # 一直超标，每一轮都白跑，最后撞 API 的 context too long。所以挑不出就得硬压。
        if H.need_compact(traj):
            idxs = H.compact_targets(traj)
            if idxs:
                merged = ' / '.join(summarize(traj[i].get('content')) for i in idxs[:4])
                traj = H.fold(traj, idxs, merged)
                log({'event': 'compact', 'folded': len(idxs), 'chars': len(merged)})
            else:
                # 没有超过 400 字的旧工具结果，就按长度砍掉最老的三成工具消息
                tool_idx = [i for i, m in enumerate(traj) if m.get('role') == 'tool']
                cut = tool_idx[:max(1, len(tool_idx) // 3)] if tool_idx else []
                if cut:
                    traj = H.fold(traj, cut, '（早期输出太长且细碎，已整体丢弃；要的话重新取一次）')
                    log({'event': 'compact_force', 'dropped': len(cut)})
                else:
                    traj = [traj[0]] + traj[-(CFG['max_steps'] // 2):] if len(traj) > 6 else traj
                    log({'event': 'compact_hard', 'left': len(traj)})

        # 静态前缀 + 轨迹 + 状态栏（状态栏每轮重写，不累积）
        traj, fixed = H.repair_trajectory(traj)
        if fixed:
            log({'event': 'repair_trajectory', 'filled': fixed})
        messages = [{'role': 'system', 'content': H.STATIC_PREFIX}] + traj + \
                   [{'role': 'user', 'content': H.state_bar(step, CFG['max_steps'], spent_today() + total,
                                                            BUDGET, started)}]
        resp = call(messages, schema)
        u = resp.get('usage') or {}
        total += cost(u)
        msg = resp['choices'][0]['message']
        traj.append({'role': 'assistant', 'content': msg.get('content') or '',
                     'tool_calls': msg.get('tool_calls')} if msg.get('tool_calls')
                    else {'role': 'assistant', 'content': msg.get('content') or ''})
        log({'step': step, 'usage': u, 'say': (msg.get('content') or '')[:200],
             'calls': [tc['function']['name'] for tc in (msg.get('tool_calls') or [])]})

        calls = msg.get('tool_calls') or []
        if not calls:
            add_spend(total)
            log({'event': 'done', 'steps': step, 'cost_cny': round(total, 5),
                 'evidence': H.has_evidence(traj)})
            return (msg.get('content') or '').strip()

        for tc in calls:
            name = tc['function']['name']
            try: args = json.loads(tc['function']['arguments'] or '{}')
            except Exception: args = {}
            # 2026-10-29：先看路径是不是另一台机器的。是就直接给一句人话，
            # 别让她拿着 $HOME/... 去 NAS 上撞四次 No such file。
            foreign = H.foreign_path_warning(args.get('path') or args.get('path_out') or '')
            if foreign and name in ('read_file', 'list_dir', 'write_file', 'tts'):
                result = {'error': foreign, 'error_class': 'fatal:路径不属于这台机器',
                          'retryable': False}
                log({'step': step, 'tool': name, 'blocked': '外来路径', 'path': str(args.get('path'))[:80]})
                traj.append({'role': 'tool', 'tool_call_id': tc['id'],
                             'content': json.dumps(result, ensure_ascii=False)})
                continue
            ok, why = H.pingpong_guard(name, args)
            if ok:
                ok, why = H.gate(name, args, T.TOOLS)
            if not ok:
                result = {'error': '被 Harness 拦下：' + why}
                log({'step': step, 'tool': name, 'blocked': why})
            else:
                try:
                    result = T.TOOLS[name]['fn'](**args)
                    fail_streak[name] = 0
                except Exception as e:
                    fail_streak[name] = fail_streak.get(name, 0) + 1
                    H.breaker_fail(name)
                    result = {'error': f'{type(e).__name__}: {e}',
                              'hint': '换个办法，别重复同一个调用' if fail_streak[name] >= 2 else '看看参数对不对'}
                    log({'step': step, 'tool': name, 'error': str(e)[:200]})
                log({'step': step, 'tool': name, 'args': summarize(args, 160),
                     'result': summarize(result, 300)})
                if 'error' in result:
                    cls, retry = H.classify_error(result['error'])
                    result['error_class'] = cls
                    result['retryable'] = retry
                    log({'step': step, 'error_class': cls, 'retryable': retry})
                else:
                    ok2, why2 = H.result_guard(name, result)
                    if not ok2:
                        traj.append({'role': 'user', 'content': f'（{why2}。别再重复，换目标或收工。）'})
                        log({'step': step, 'stuck_same_result': name})
            traj.append({'role': 'tool', 'tool_call_id': tc['id'],
                         'content': json.dumps(result, ensure_ascii=False)[:6000]})
            if fail_streak.get(name, 0) >= 2:
                traj.append({'role': 'user', 'content': f'（{name} 已经连败两次，换方法。）'})
            else:
                nudge = H.loop_guard_nudge(name, args)
                if nudge:
                    traj.append({'role': 'user', 'content': nudge})
                    log({'step': step, 'tool': name, 'nudge': '即将重复调用'})

    add_spend(total)
    log({'event': 'max_steps', 'steps': step - 1, 'cost': round(total, 5)})
    # 2026-10-29 改：撞上限不再直接撂挑子。
    #   原来只说「走到第 30 步还没收工」，等于白干一趟还把问题原样丢回去（主人 22:24 就是这么被噎住的）。
    #   现在先让模型用已经拿到的东西给一句结论，再说明为什么停。
    try:
        traj, _ = H.repair_trajectory(traj)
        ask = [{'role': 'system', 'content': H.STATIC_PREFIX}] + traj + [
            {'role': 'user', 'content': '（步数用完了。不要再用工具。只用你上面已经拿到的结果，'
                                       '直接回答主人最初的问题；哪一部分没做到，就明说是哪一步断的。）'}]
        resp2 = call(ask, [])   # 收尾不带工具，只让它把话说完
        msg2 = resp2['choices'][0]['message']
        u2 = resp2.get('usage') or {}
        total += cost(u2)
        add_spend(cost(u2))
        ans = (msg2.get('content') or '').strip()
        if ans:
            log({'event': 'max_steps_summary', 'chars': len(ans)})
            return ans + f'\n\n（这条是撞到 {CFG["max_steps"]} 步上限后收的尾，花了 {total:.4f} 元。）'
    except Exception as e:
        log({'event': 'max_steps_summary_fail', 'err': str(e)[:120]})
    return f'走到第 {CFG["max_steps"]} 步还没收工，也没来得及收尾。花了 {total:.4f} 元。'

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python3 agent.py "目标"'); sys.exit(2)
    print(run(sys.argv[1]))
