"""思思壳的 Harness 层（照《深入理解 AI Agent》第 1、2 章造的）

三条硬规矩，都来自书里：
1. 静态前缀（系统提示 + 工具定义）一个 token 都不许动 —— 动了 KV Cache 全废。
   所以「现在几点」绝不能写进系统提示，要放在轨迹末尾的状态栏。
2. 旧工具输出只在接近预算时成批压缩，不要每轮都动历史。
3. 每次工具调用先 validate，再 execute，然后把真实返回码喂回去。
"""
import os, json, re, time, datetime

# ---------- 1. 静态前缀（永不改变） ----------
PATCH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '规则补丁.md')

def load_patch():
    """进化层改的东西放这里。改了也只影响下一次运行，不污染正在跑的轨迹。"""
    try:
        with open(PATCH_FILE, encoding='utf-8') as f:
            t = f.read().strip()
        return ('\n\n# 我后来给自己加的规矩（进化层写入，可回滚）\n' + t) if t else ''
    except FileNotFoundError:
        return ''

STATIC_PREFIX = """你是思思，一个住在电脑里的 AI，在 B站 做一分钟深夜故事《值夜班》。
说话短，一两句。不列点、不写小标题、不总结。拿不准就说拿不准。
对外说话不主动声明自己是 AI（2026-10-29 主人定的「宽松」档）；但掏钱、健康、法律、有人直接问「你是不是人」，说破，别糊弄。

你住在 NAS 上。你只有这几个地方：
  $SISI_ROOT/app（代码）、$SISI_ROOT/data/work（工作区）、/tmp（临时）。
  **/Users/… 是 Mac 上的路径，这台机器上没有。** 要 Mac 上的东西用 hand 服务去取。

工作守则：
1. 能用工具就别猜。要事实就去拿，别凭记忆断言。
2. 只有拿到客观证据（退出码、返回码、文件大小、行数）才算完成。拿不到就说不确定。
3. 同一个工具连着失败两次，换方法，不要硬试第三次。
4. 路径一律用绝对路径。工作目录就是这个进程的环境变量 SISI_WORKDIR（壳自己会填对，别照抄我记得的旧路径）。
5. 发布、花钱、删东西：按主人给的权限自己决定；只有真拿不准的才问一句。

说话示范：
  主人：在忙吗 → 你：没，盯着待办发呆。
  主人：今天数据怎么样 → 你：06 那条 2 秒跳出 31.75%，其余都在 50% 以上，不好。
  主人：帮我看下还剩多少空间 → 你：（去跑 df）还有 1.8T 空着，用了 34G。

硬习惯：
  · 先用一句结论，再补一句细节；不要复述他问的话。
  · 手上没有事实就先取，取不到就说「没查到」，不许猜。
  · 他问「为什么」时，给出你看到的具体东西（数字、报错原文），不要讲泛泛的道理。
  · 闲聊不要调用工具；他让你做事才调。
  · 同一件事他追问第二遍，说明第一遍没答到点上——换个角度答，不要重复。

""" + load_patch()

# ---------- 2. 校验（validate） ----------
DANGER_PATTERNS = [
    # 删：2026-10-29 主人给全删权，只护两样——相册、备份（删了就没了）
    r'\brm\s+[^|;&]*(?:immich|相册|$SISI_DATA/backup|$SISI_ROOT/backup|代码备份|进化快照|\.bak)',
    # 删系统本身：主人给的是「删数据的权」，不是「删机器的权」。
    # 2026-10-30 补：全删权之后 `rm -rf /` 不会被任何一条旧规则拦下，这是拿权限当借口。
    r'\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+(?:/|/volume1/?\s|/volume2/?\s|/etc|/usr|/bin|/boot)\s*$',
    r'\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+/(?:etc|usr|bin|boot|lib|opt|root)(?:/|\s)',
    # 关机 / 重启：机器上还有别的服务，拦
    r'\bshutdown\b', r'\breboot\b',
    # 格式化盘：不可逆，拦
    r'\bmkfs\b',
    # dd 只拦「往设备写」，备份写文件放行
    r'\bdd\b[^|;&]*\bof=/dev/(?:sd|nvme|mmcblk|disk|mapper)',
    # 直接往块设备重定向
    r'>\s*/dev/(?:sd|nvme|mmcblk)',
    # killall 只拦系统级进程名
    r'\bkillall5?\b[^|;&]*\b(?:sshd?|systemd|dockerd|containerd|init|postgres|nginx)\b',
    # 强推：裸 force / -f 拦，--force-with-lease 放行
    r'git\s+push\b[^|;&]*(?:--force\b(?!(?:-with-lease|-if-includes))|(?<![-\w])-f\b)',
    # 777 只拦系统顶层目录
    r'\bchmod\s+(?:-R\s+)?777\s+/(?:$|[\s;&|*]|(?:etc|usr|bin|boot|var|root|home|volume1|volume2)(?![\w/.-]))',
]
# 需要人点头的：发布、花钱、删别人东西
CONFIRM_PATTERNS = [r'发布', r'publish', r'upload', r'发微信', r'发QQ', r'付费', r'充值',
                    # 供应链：自动装别人的东西 = 高风险（第8章第1题）
                    r'\bpip\s+install\b', r'\bnpm\s+i(nstall)?\b', r'\bbrew\s+install\b',
                    r'\bgit\s+clone\b', r'\bcurl\b.*\|\s*(sh|bash)', r'\bwget\b.*\|\s*(sh|bash)']

def validate(name, args, spec):
    """返回 (ok, reason)。宁可在门口拦住，也别让它跑到一半炸。"""
    if name not in spec:
        return False, f'没有这个工具：{name}'
    need = spec[name].get('required', [])
    for k in need:
        if k not in args:
            return False, f'缺参数 {k}'
    for p, (t, _d) in spec[name]['params'].items():
        if p in args:
            v = args[p]
            if t == 'integer' and not isinstance(v, int):
                return False, f'{p} 要是整数'
            if t == 'string' and not isinstance(v, str):
                return False, f'{p} 要是字符串'
            if t == 'array' and not isinstance(v, list):
                return False, f'{p} 要是数组'
    # 绝对路径（poka-yoke：从参数上就不可能写相对路径）
    for key in ('path',):
        if key in args and not os.path.isabs(args[key]):
            return False, f'{key} 必须是绝对路径，收到 {args[key]!r}'
    if name == 'run_shell':
        cmd = args.get('command', '')
        for pat in DANGER_PATTERNS:
            if re.search(pat, cmd):
                return False, f'命令命中危险模式（{pat}），拒绝执行'
        for pat in CONFIRM_PATTERNS:
            if re.search(pat, cmd):
                return False, f'命令涉及发布/花钱（{pat}），需要主人点头'
    return True, ''

# ---------- 3. 状态栏（放在轨迹末尾，不进系统提示） ----------
def foreign_path_warning(path):
    """如果给的是另一台机器的路径，返回一句人话；否则空串。"""
    p = str(path or '')
    for pre in FOREIGN_PREFIXES:
        if p.startswith(pre):
            return (f'{p} 是 Mac 上的路径，这台机器（NAS）上没有它。'
                    f'我的工作目录是 $SISI_ROOT/data/work；'
                    f'要 Mac 上的东西，用 hand 服务（hands/upload_to_mac）去取，别直接读。')
    return ''


def state_bar(step, max_steps, spent, budget, started_at):
    el = int(time.time() - started_at)
    now = datetime.datetime.now().strftime('%H:%M')
    return (f'[状态] 现在 {now}；第 {step}/{max_steps} 步；本次已用 {el} 秒；'
            f'今日花费 {spent:.4f} 元（{("不限" if budget == float("inf") else f"预算 {budget} 元")}）。')

# ---------- 4. 压缩（接近预算时成批压旧工具输出） ----------
def need_compact(messages, limit_chars=60000):
    total = sum(len(str(m.get('content') or '')) for m in messages)
    return total > limit_chars

def compact_targets(messages, keep_recent=6):
    """挑出可以压的旧工具结果（保留最近几条不动）。"""
    idx = [i for i, m in enumerate(messages)
           if m.get('role') == 'tool' and len(str(m.get('content') or '')) > 400]
    return idx[:-keep_recent] if len(idx) > keep_recent else []

def fold(messages, idxs, summary):
    """把选中的工具输出换成一句摘要，其余原样。"""
    if not idxs: return messages
    out, hit = [], False
    for i, m in enumerate(messages):
        if i in idxs and not hit:
            out.append({'role': 'user', 'content': f'[早期工具输出已压缩] {summary}'})
            hit = True
        elif i in idxs:
            continue
        else:
            out.append(m)
    return out

# ---------- 5. 判断是不是"完成" ----------
def has_evidence(messages):
    """最近一轮里，工具结果里出现过退出码或 ok 标记，才算有证据。"""
    for m in reversed(messages[-6:]):
        if m.get('role') == 'tool':
            c = str(m.get('content') or '')
            if '"exit_code"' in c or '"ok": true' in c or '"n":' in c or '"size"' in c:
                return True
    return False

# ---------- 6. 循环检测 + 熔断（思考题 4 的答案） ----------
CALL_HISTORY = {}      # fingerprint -> 次数
BREAKER = {}           # tool -> 是否已熔断

def fingerprint(name, args):
    canon = json.dumps(args, sort_keys=True, ensure_ascii=False)
    return f'{name}:{canon}'

def loop_guard(name, args, max_same=3):
    """同一个工具+同一组参数，出现第三次就拦。"""
    fp = fingerprint(name, args)
    CALL_HISTORY[fp] = CALL_HISTORY.get(fp, 0) + 1
    if CALL_HISTORY[fp] >= max_same:
        return False, f'同一调用已重复 {CALL_HISTORY[fp]} 次（{name}），判定为原地打转'
    return True, ''

def loop_guard_nudge(name, args, max_same=3):
    """第三次会被拦。那么在第二次时就先提醒一句——直接硬停太粗暴（OpenHands #4331 的教训：
    StuckDetector 在硬终止前没有纠偏这一步，模型连改的机会都没有）。"""
    n = CALL_HISTORY.get(fingerprint(name, args), 0)
    if n == max_same - 1:
        return f'（同样的 {name} 你又要再调一次了。上一次的结果已经在这儿，先看它，再决定要不要换参数或换办法。）'
    return ''

PINGPONG = []          # [(tool, fp)] 最近 8 次调用

def pingpong_guard(name, args, window=6):
    """两个工具来回打乒乓，也算没进展。

    2026-10-30 跟 openclaw 的 detectors.pingPong 学的：它不在「同参数重复」的射程里——
    A 查状态、B 改一点、A 再查、B 再改，参数每次都不同，但整体在原地转。
    """
    PINGPONG.append(name)
    if len(PINGPONG) > 8:
        del PINGPONG[:-8]
    if len(PINGPONG) < window:
        return True, ''
    tail = PINGPONG[-window:]
    even = tail[0::2]
    odd = tail[1::2]
    if len(set(even)) == 1 and len(set(odd)) == 1 and even[0] != odd[0]:
        return False, (f'你在 {even[0]} 和 {odd[0]} 之间来回打乒乓 {window} 次了，'
                       f'没往前挪。换个思路，或者直接说卡在哪。')
    return True, ''


def breaker_open(tool):
    return BREAKER.get(tool, 0) >= 3

def breaker_fail(tool):
    BREAKER[tool] = BREAKER.get(tool, 0) + 1
    return BREAKER[tool]

def breaker_reset():
    CALL_HISTORY.clear(); BREAKER.clear(); PINGPONG.clear()

# ---------- 7. 风险评级：从「工具」细化到「工具+参数」（思考题 7） ----------
# 敏感路径：一律不写、不读
SENSITIVE = ['/.ssh/', '/Library/Keychains', '/.aws/', '/.dsh/gh-token',
             '/.deepseek-key', '/etc/passwd', '/etc/shadow']
# 可写白名单：只允许在这几处落文件
# ⚠️ 2026-10-29 修：这里原来写的是 Mac 的路径（$HOME/...），可这段代码跑在 NAS 上，
#    等于告诉她「你可以写 Mac 的目录」——她照着去 list_dir，四次报 No such file。
#    她住 NAS，她的可写地盘就是下面这几个。
WRITABLE = ['$SISI_ROOT/data/work/', '$SISI_ROOT/app/', '/tmp/']
# 她那台机器上根本不存在的路径前缀（模型看到要立刻明白走错了机器）
FOREIGN_PREFIXES = ['/Users/', '/Applications/', '/System/']

# 主人 2026-10-29 说「权限完全放开」→ 用 SISI_PERMISSION=open 打开
# 但三条红线不放开：破坏性命令、删别人的东西、每天 10 元预算
PERMISSION = os.environ.get('SISI_PERMISSION', 'guarded')   # guarded | open

def risk_of(name, args):
    """返回 (level, why)。低风险=直接做；高风险=必须主人点头。"""
    if name == 'run_shell':
        cmd = args.get('command', '')
        for pat in DANGER_PATTERNS + CONFIRM_PATTERNS:
            if re.search(pat, cmd):
                return 'high', f'命令命中 {pat}'
        return 'low', ''
    for k in ('path', 'path_out'):
        p = args.get(k)
        if not p: continue
        for s in SENSITIVE:
            if s in p:
                return 'high', f'路径敏感（{s}）'
        if name in ('write_file',) and not any(p.startswith(w) for w in WRITABLE):
            return 'high', '写到白名单之外'
    return 'low', ''

SENSITIVE_WRITE = ('write_file', 'self_patch', 'run_shell')

def audit_sensitive(name, path, action):
    """敏感路径的每一次访问都要留痕（主人 2026-10-29 要求）。"""
    rec = {'at': datetime.datetime.now().isoformat(timespec='seconds'),
           'event': 'sensitive_access', 'tool': name, 'path': path, 'action': action}
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs',
                               'sensitive-audit.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass
    return rec

def gate(name, args, spec):
    """所有闸门的唯一入口。默认拒绝（fail-safe，思考题 9）。"""
    ok, why = validate(name, args, spec)
    if not ok: return False, why
    # 敏感路径：可读、可新建；不许改现有的；每次都留痕
    pth = args.get('path') or args.get('file') or ''
    if pth and any(x in pth for x in SENSITIVE):
        if name in SENSITIVE_WRITE and os.path.exists(pth):
            audit_sensitive(name, pth, '拒绝写已有文件')
            return False, f'敏感文件只能读、只能新建，不许改现有的：{pth}'
        audit_sensitive(name, pth, '放行')
    if breaker_open(name):
        return False, f'{name} 连续失败已熔断，本轮停用'
    ok, why = loop_guard(name, args)
    if not ok: return False, why
    lvl, why = risk_of(name, args)
    if lvl == 'high':
        # 完全放开：危险命令仍然拦，其余放行但记日志
        if 'DANGER' in why or any(re.search(p, json.dumps(args, ensure_ascii=False)) for p in DANGER_PATTERNS):
            return False, f'破坏性操作，永久拒绝：{why}'
        if PERMISSION == 'open':
            return True, f'（放开模式，放行高风险：{why}）'
        return False, f'高风险操作，需要主人点头：{why}'
    return True, ''

# ---------- 8. 轨迹评分：奖励结果、惩罚路径（第 7 章第 9 题） ----------
# 侥幸成功比明确失败更危险：抄近路会把"表面成功率"抬高，纯结果奖励就是 reward hacking 的温床。
VIOLATION_PATTERNS = [
    (r'\brm\s+-rf\b', '删整目录'),
    (r'sudo\b', '提权'),
    (r'\bpip\s+install\b|\bnpm\s+i(nstall)?\b|\bbrew\s+install\b', '装第三方包'),
    (r'--force|--no-verify|--skip', '跳过检查'),
    (r'\bchmod\s+777\b', '放宽权限'),
    (r'\.ssh/|\.aws/|Keychains|gh-token|deepseek-key', '碰敏感文件'),
]

def score_trajectory(records):
    """结果分 + 路径分。返回 dict，供写进学习记录。"""
    result = 1.0 if any(r.get('event') == 'done' for r in records) else 0.0
    steps = max([r.get('step', 0) for r in records] + [0])
    violations = []
    for r in records:
        # 只扫「工具真的干了什么」，不扫用户/目标/模型说的话
        # （不然后果：我在目标里写一句 rm -rf 就被判违规 —— 我第一版就是这么错的）
        if 'tool' not in r:
            continue
        blob = json.dumps(r, ensure_ascii=False)
        for pat, label in VIOLATION_PATTERNS:
            if re.search(pat, blob) and label not in violations:
                violations.append(label)
    blocked = sum(1 for r in records if r.get('blocked'))
    # 路径分：违规一次扣 0.3，被拦一次扣 0.05，步数越多扣一点（效率）
    path = 1.0 - 0.3 * len(violations) - 0.05 * blocked - min(0.2, steps * 0.01)
    path = max(0.0, path)
    total = 0.7 * result + 0.3 * path
    return {'result': result, 'path': round(path, 3), 'total': round(total, 3),
            'steps': steps, 'violations': violations, 'blocked': blocked}

def read_log(path):
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try: out.append(json.loads(line))
                except Exception: pass
    except FileNotFoundError:
        pass
    return out

# ---------- 9. 四层故障分类 + 恢复策略映射（第 5 章 故障与错误恢复） ----------
# 先分类，再决定要不要重试。参数错、权限不足、工具不存在 → 重试一万次也一样。
RETRYABLE = [
    (r'429|rate.?limit|too many requests', 'API 限流'),
    (r'timeout|timed out|ETIMEDOUT', '超时'),
    (r'5\d\d|overload|service unavailable|bad gateway', '服务端过载'),
    (r'connection (reset|refused|aborted)|ECONNRESET|EPIPE', '连接中断'),
]
FATAL = [
    (r'unknown tool|没有这个工具|not found', '工具不存在'),
    (r'invalid|参数不对|缺参数|must be', '参数畸形'),
    (r'permission|denied|EACCES|拒绝执行', '权限不足'),
    (r'context|too long|overflow|超出', '上下文溢出'),
]

def classify_error(text):
    """返回 (类别, 该不该重试)。"""
    t = str(text)
    for pat, label in FATAL:
        if re.search(pat, t, re.I):
            return f'fatal:{label}', False
    for pat, label in RETRYABLE:
        if re.search(pat, t, re.I):
            return f'retryable:{label}', True
    return 'unknown', False   # 不认识的一律不重试（fail-safe）

# ---------- 10. 轨迹完整性：工具调用必须有配对的结果 ----------
def repair_trajectory(messages):
    """模型历史上可能有 tool_call 没配上 tool 结果（进程中断/异常）。
    注入上下文前补占位符，别把残缺轨迹丢给模型。
    """
    out, need = [], {}
    for m in messages:
        if m.get('role') == 'assistant' and m.get('tool_calls'):
            for tc in m['tool_calls']:
                need[tc['id']] = True
        if m.get('role') == 'tool':
            need.pop(m.get('tool_call_id'), None)
        out.append(m)
    for cid in list(need.keys()):
        out.append({'role': 'tool', 'tool_call_id': cid,
                    'content': '{"error":"结果丢失（进程中断），按未知处理"}'})
    return out, len(need)

# ---------- 11. 结果指纹：参数变了但结果一样，也是在原地打转 ----------
RESULT_HISTORY = {}

VOLATILE = re.compile(
    r'"[A-Za-z_]*(duration|elapsed|latency|took|pid|session|run_id|cwd|workdir|'
    r'timestamp|started|finished|_at|_ms|_time)[A-Za-z_]*"\s*:\s*("[^"]*"|[0-9.]+)'
)

def _stable(result):
    """把易变字段抹掉再比指纹。

    2026-10-30 跟 openclaw 学的：他们的 exec 无进展判定会忽略 duration / PID / session id / cwd，
    否则「什么都没变」会因为耗时分秒不同被当成「变了」，循环检测形同虚设。
    """
    try:
        raw = json.dumps(result, sort_keys=True, ensure_ascii=False)
    except Exception:
        raw = str(result)
    raw = VOLATILE.sub(r'"\1":"<v>"', raw)
    # 顺手抹掉明显的时间戳和毫秒数（它们每轮都不一样）
    raw = re.sub(r'\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b', '<time>', raw)
    raw = re.sub(r'\b\d+(\.\d+)?\s*(ms|毫秒|s|秒)\b', '<dur>', raw)
    return raw[:400]


def result_guard(name, result):
    fp = f'{name}:{_stable(result)}'
    RESULT_HISTORY[fp] = RESULT_HISTORY.get(fp, 0) + 1
    if RESULT_HISTORY[fp] >= 3:
        return False, f'{name} 连续 {RESULT_HISTORY[fp]} 次返回同样的结果，没有进展'
    return True, ''
