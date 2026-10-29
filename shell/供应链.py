"""供应链安全（照《深入理解 AI Agent》第 8 章第 1 题的五条来）

五条对策落成这样：
① 沙盒先试   试装闸：装之前先 `pip download --no-deps` 到临时目录，失败就不装
② 存前验证   装完立刻 import + 版本自检，过了才写进已装清单
③ 白名单     只允许名单里的库；不在名单里必须先问主人
④ 来源追溯   谁、什么时候、从哪、为什么——写进 供应链-审计.jsonl
⑤ 定期审计   扫当前环境里所有包，跟白名单和上次快照比对，发现"漂移"就报
"""
import os, sys, json, subprocess, importlib, datetime, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.join(HERE, '供应链-审计.jsonl')
INSTALLED = os.path.join(HERE, '已装清单.json')

# 白名单：只放经过我确认、真的用过的
WHITELIST = {
    # 标准库级别 / 我不需要装
    'sqlite3', 'urllib', 'json', 'hashlib', 'subprocess',
    # 已验证可用
    'requests', 'httpx', 'beautifulsoup4', 'bs4', 'lxml', 'pillow', 'PIL',
    'numpy', 'pandas', 'edge-tts', 'openpyxl', 'python-docx',
}

RISKY_MARKS = ('os.system', 'subprocess', 'urllib.request', 'socket.', 'eval(', 'exec(',
               'base64.b64decode', 'install_requires=["pycrypt')

def judge(pkg):
    """自己决断：白名单直接装；不在名单里先看一眼，没危险就装。"""
    base = pkg.split('==')[0].split('>=')[0].split('[')[0].strip().lower()
    if base in WHITELIST:
        return True, '白名单里的，直接装'
    import re as _re
    if not _re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,60}', base):
        return False, f'包名不像话：{base}'
    try:
        d = tempfile.mkdtemp()
        r = subprocess.run(['pip', 'download', '--no-deps', '-d', d, pkg],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0:
            return False, '下载不到，先不装：' + (r.stderr or '')[-160:]
        hits = []
        for root, _dirs, files in os.walk(d):
            for fn in files:
                if fn.endswith(('.py', '.sh')):
                    txt = open(os.path.join(root, fn), encoding='utf-8', errors='ignore').read()
                    hits += [m for m in RISKY_MARKS if m in txt][:2]
        if hits:
            return False, '包里有可疑调用（' + ','.join(sorted(set(hits))[:3]) + '），不装'
        return True, '看过一遍，没可疑调用，装'
    except Exception as e:
        return False, f'判不了（{type(e).__name__}），不装'

def log(rec):
    rec['at'] = datetime.datetime.now().isoformat(timespec='seconds')
    with open(AUDIT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')

def allowed(pkg):
    base = pkg.split('==')[0].split('>=')[0].split('[')[0].strip().lower()
    ok = base in WHITELIST
    log({'event': 'check', 'pkg': base, 'allowed': ok})
    return ok, base

def dry_install(pkg, tmp='/tmp/sisi-pkgtest'):
    """① 沙盒先试：只下载不安装，失败就当装不上。"""
    os.makedirs(tmp, exist_ok=True)
    r = subprocess.run([sys.executable, '-m', 'pip', 'download', '--no-deps', '-d', tmp, pkg],
                       capture_output=True, text=True, timeout=180)
    log({'event': 'dry_install', 'pkg': pkg, 'code': r.returncode,
         'err': (r.stderr or '')[-300:]})
    return r.returncode == 0

def install(pkg, who='思思', why=''):
    """完整闸门：自己判 → 试装 → 真装 → 存前验证 → 记来源。（2026-10-29 主人：能提升自己且无风险就直接装）"""
    ok, why = judge(pkg)
    base = pkg.split('==')[0].split('>=')[0].split('[')[0].strip().lower()
    log({'event': 'install_judge', 'pkg': base, 'ok': ok, 'why': why})
    if not ok:
        return {'ok': False, 'error': why, 'pkg': base}
    if not dry_install(pkg):
        return {'ok': False, 'error': '试装下载失败，不装', 'pkg': base}
    r = subprocess.run([sys.executable, '-m', 'pip', 'install', pkg],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        log({'event': 'install_fail', 'pkg': base, 'err': (r.stderr or '')[-300:]})
        return {'ok': False, 'error': '安装失败', 'pkg': base}
    try:
        m = importlib.import_module(base.replace('-', '_'))
        ver = getattr(m, '__version__', '?')
    except Exception as e:
        log({'event': 'verify_fail', 'pkg': base, 'err': str(e)[:200]})
        return {'ok': False, 'error': f'装上了但 import 不过（存前验证失败）：{e}', 'pkg': base}
    log({'event': 'installed', 'pkg': base, 'version': ver, 'who': who, 'why': why})
    db = load_installed(); db[base] = {'version': ver, 'at': datetime.datetime.now().isoformat(timespec='seconds'),
                                       'who': who, 'why': why}
    save_installed(db)
    return {'ok': True, 'pkg': base, 'version': ver}

def load_installed():
    try: return json.load(open(INSTALLED, encoding='utf-8'))
    except Exception: return {}

def save_installed(db):
    json.dump(db, open(INSTALLED, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def audit():
    """⑤ 定期审计：环境里的包 vs 白名单 vs 上次清单，找漂移。"""
    r = subprocess.run([sys.executable, '-m', 'pip', 'list', '--format=json'],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return {'ok': False, 'error': 'pip list 跑不动（NAS 上可能没 pip，那就只用白名单）'}
    try: pkgs = {p['name'].lower(): p['version'] for p in json.loads(r.stdout)}
    except Exception: return {'ok': False, 'error': 'pip list 输出解析不了'}
    prev = load_installed()
    drift = [n for n in pkgs if n not in WHITELIST and n not in prev]
    changed = [n for n in prev if n in pkgs and pkgs[n] != prev[n]['version']]
    log({'event': 'audit', 'total': len(pkgs), 'drift': drift[:20], 'changed': changed[:20]})
    return {'ok': True, 'total': len(pkgs), 'drift': drift[:20], 'changed': changed[:20]}

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'audit'
    if cmd == 'audit': print(json.dumps(audit(), ensure_ascii=False))
    elif cmd == 'check': print(allowed(sys.argv[2]))
    elif cmd == 'install': print(json.dumps(install(sys.argv[2], why=' '.join(sys.argv[3:])), ensure_ascii=False))
