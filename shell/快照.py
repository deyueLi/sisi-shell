"""进化前先拍快照，出问题能回退到之前那一版。

拍什么：规则补丁.md、config.json、进化登记、todo.json，外加每一个的 sha256。
存在 备份/进化快照/<时间戳>/，manifest.json 记下每个文件的哈希。
回退：restore(<时间戳>)，哈希对不上就不回退（宁可停下，也不把坏文件覆盖回去）。
"""
import os, sys, json, shutil, hashlib, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.environ.get('SISI_WORKDIR') or HERE
SNAP_ROOT = os.path.join(os.path.dirname(W), '进化快照') if os.path.isdir(os.path.dirname(W)) else os.path.join(HERE, '进化快照')
WATCH = ['规则补丁.md', 'config.json', '进化-待验证.json', 'todo.json']
HISTORY = os.path.join(HERE, '进化历史.md')

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def snapshot(reason='进化前'):
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    d = os.path.join(SNAP_ROOT, ts)
    os.makedirs(d, exist_ok=True)
    man = {'ts': ts, 'at': datetime.datetime.now().isoformat(timespec='seconds'),
           'reason': reason, 'files': {}}
    for name in WATCH:
        src = os.path.join(HERE, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(d, name)
        shutil.copy2(src, dst)
        man['files'][name] = {'sha256': sha(dst), 'size': os.path.getsize(dst)}
    json.dump(man, open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    note(f"- {man['at']} 快照 {ts}（{reason}）：{', '.join(man['files']) or '无文件'}\n")
    return ts, man

def note(line):
    if not os.path.exists(HISTORY):
        open(HISTORY, 'w', encoding='utf-8').write('# 进化历史（每次改动与回退）\n\n')
    open(HISTORY, 'a', encoding='utf-8').write(line)

def list_snaps():
    if not os.path.isdir(SNAP_ROOT): return []
    return sorted(os.listdir(SNAP_ROOT), reverse=True)

def restore(ts, why=''):
    d = os.path.join(SNAP_ROOT, ts)
    man_p = os.path.join(d, 'manifest.json')
    if not os.path.exists(man_p):
        raise SystemExit(f'快照 {ts} 不存在')
    man = json.load(open(man_p, encoding='utf-8'))
    bad = []
    for name, info in man['files'].items():
        src = os.path.join(d, name)
        if not os.path.exists(src) or sha(src) != info['sha256']:
            bad.append(name)
    if bad:
        note(f"- 回退 {ts} 被拒绝：快照自身校验不过（{bad}）\n")
        raise SystemExit(f'快照损坏，拒绝回退：{bad}')
    for name in man['files']:
        shutil.copy2(os.path.join(d, name), os.path.join(HERE, name))
    note(f"- {datetime.datetime.now():%F %T} 回退到 {ts}（{why}）：{', '.join(man['files'])}\n")
    return list(man['files'])

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'snap'
    if cmd == 'snap':
        print('快照:', snapshot(sys.argv[2] if len(sys.argv) > 2 else '手动'))
    elif cmd == 'list':
        for t in list_snaps()[:10]: print(t)
    elif cmd == 'restore':
        print('已回退:', restore(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else '手动'))
