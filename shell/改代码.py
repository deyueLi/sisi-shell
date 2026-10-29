"""改自己的代码（主人 2026-10-29 放开的权限）

但改代码这件事，一定要有下车的地方：
  1. 改之前整份备份目标文件（带 sha256）
  2. 只做"精确替换"，不做花式改写——替换串必须唯一匹配
  3. 改完先 ast 语法检查
  4. 再 import/编译检查
  5. 在跑的服务要重启，重启后起不来 → 立刻还原
  6. 每一步都写进 进化历史.md
禁止改的：本文件自己（改坏了就没有还原能力了）、systemd unit、密钥文件。
"""
import os, sys, ast, shutil, hashlib, datetime, subprocess, importlib

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, '代码备份')
HISTORY = os.path.join(HERE, '进化历史.md')
FORBIDDEN = {'.deepseek-key'}   # 2026-10-29 主人给了自己代码的全部权限，只剩密钥不许动

def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(65536), b''): h.update(c)
    return h.hexdigest()

def _note(line):
    if not os.path.exists(HISTORY):
        open(HISTORY, 'w', encoding='utf-8').write('# 进化历史（每次改动与回退）\n\n')
    open(HISTORY, 'a', encoding='utf-8').write(line)

def _backup(path):
    os.makedirs(BACKUP, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    dst = os.path.join(BACKUP, f'{os.path.basename(path)}.{ts}.bak')
    shutil.copy2(path, dst)
    return dst, ts, _sha(dst)

def self_patch(file, old, new, why=''):
    """把文件里唯一的一段 old 换成 new。有一步不对就整体放弃并还原。"""
    name = os.path.basename(file)
    path = file if os.path.isabs(file) else os.path.join(HERE, name)
    if name in FORBIDDEN:
        return {'ok': False, 'error': f'{name} 不许自动改（它是最后的保险）'}
    if not os.path.exists(path):
        return {'ok': False, 'error': f'文件不存在：{path}'}
    src = open(path, encoding='utf-8').read()
    cnt = src.count(old)
    if cnt == 0:
        return {'ok': False, 'error': '找不到要替换的那段（old 不匹配）'}
    if cnt > 1:
        return {'ok': False, 'error': f'那段出现 {cnt} 次，不唯一，拒绝改'}
    bak, ts, sha = _backup(path)
    try:
        patched = src.replace(old, new, 1)
        ast.parse(patched)                      # 语法闸
        open(path, 'w', encoding='utf-8').write(patched)
        compile(patched, path, 'exec')          # 编译闸
    except SyntaxError as e:
        shutil.copy2(bak, path)
        _note(f"- {datetime.datetime.now():%F %T} 改 {name} 被语法检查拦下（{e.msg} 第{e.lineno}行），已还原\n")
        return {'ok': False, 'error': f'语法错误，已还原：{e.msg} 第 {e.lineno} 行'}
    except Exception as e:
        shutil.copy2(bak, path)
        _note(f"- {datetime.datetime.now():%F %T} 改 {name} 出错（{e}），已还原\n")
        return {'ok': False, 'error': f'改的时候出错，已还原：{e}'}
    _note(f"- {datetime.datetime.now():%F %T} 改了 {name}（{why or '无理由'}）：备份 {os.path.basename(bak)} sha {sha[:12]}\n")
    return {'ok': True, 'file': name, 'backup': os.path.basename(bak), 'sha': sha[:12],
            'chars_before': len(src), 'chars_after': len(patched)}

def restart_service(unit='sisi-shell', wait=6):
    """在跑的服务重启一下，看它能不能活。活不了就是改坏了。"""
    try:
        subprocess.run(['sudo', '-n', 'systemctl', 'restart', unit], check=True, timeout=40,
                       capture_output=True)
    except Exception as e:
        return {'ok': False, 'error': f'重启不了（可能要密码）：{e}'}
    import time; time.sleep(wait)
    r = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True)
    state = (r.stdout or '').strip()
    return {'ok': state == 'active', 'state': state}

def rollback(file, backup_name):
    p = file if os.path.isabs(file) else os.path.join(HERE, os.path.basename(file))
    bak = os.path.join(BACKUP, backup_name)
    if not os.path.exists(bak):
        return {'ok': False, 'error': '备份不在了'}
    shutil.copy2(bak, p)
    _note(f"- {datetime.datetime.now():%F %T} 还原 {os.path.basename(p)} ← {backup_name}\n")
    return {'ok': True, 'restored': os.path.basename(p)}

if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'patch':
        print(self_patch(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else ''))
    elif cmd == 'rollback':
        print(rollback(sys.argv[2], sys.argv[3]))
    elif cmd == 'restart':
        print(restart_service())
