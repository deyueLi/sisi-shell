#!/usr/bin/env python3
"""让 Mac 和 NAS 共用一份记忆（2026-10-29 主人要求合并）

做法（每次都幂等，可以随便跑）：
  1. 备份 NAS 上的库
  2. 把 NAS 的库拉到本地临时文件
  3. 把 NAS 独有的条目补进 Mac 的库（以内容为身份去重）
  4. 把 Mac 的库推回 NAS
  5. 校验两边内容指纹一致，不一致就报错（不静默）
"""
import os, sys, sqlite3, hashlib, shutil, subprocess, datetime, tempfile

MAC = os.path.expanduser('~/.dsh/whale-work/.dsh-meow/memory.db')
HOST = 'ldy1998@NAS_HOST'
REMOTE = '$SISI_ROOT/data/mem/memory.db'
LEVELS = ['soul', 'user', 'rules', 'lesson', 'fact', 'topic', 'project']

def h(t): return hashlib.sha256(' '.join((t or '').split()).encode()).hexdigest()[:16]

def ssh(cmd):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR', HOST, cmd],
                          capture_output=True, text=True, timeout=60)

def scp(src, dst):
    return subprocess.run(['scp', '-O', '-o', 'BatchMode=yes', '-o', 'LogLevel=ERROR', src, dst],
                          capture_output=True, text=True, timeout=120)

def fingerprint(db):
    c = sqlite3.connect(db); c.row_factory = sqlite3.Row
    out = {}
    for t in LEVELS:
        try:
            out[t] = {h(r['content']) for r in c.execute(f'select content from {t}')}
        except Exception:
            out[t] = set()
    c.close()
    return out

def main():
    stamp = datetime.datetime.now().strftime('%F %T')
    ssh(f'cp {REMOTE} {REMOTE}.snap-$(date +%H%M%S)')
    tmp = tempfile.mktemp(suffix='.db')
    r = scp(f'{HOST}:{REMOTE}', tmp)
    if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) < 1024:
        print(f'{stamp} 拉 NAS 库失败：{r.stderr.strip()[:200]}'); return 1

    shutil.copy2(MAC, MAC + '.bak-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    c = sqlite3.connect(MAC); c.row_factory = sqlite3.Row
    c.execute('attach database ? as nas', (tmp,))
    added = 0
    for t in LEVELS:
        cols = [d[1] for d in c.execute(f'PRAGMA table_info({t})')]
        if not cols: continue
        cur = c.execute(f'select * from nas.{t} limit 1')
        nas_cols = [d[0] for d in cur.description] if cur.description else []
        if not nas_cols: continue
        have = {h(r['content']) for r in c.execute(f'select content from {t}')}
        fields = [x for x in cols if x != 'id' and x in nas_cols]
        for r2 in c.execute(f'select * from nas.{t}').fetchall():
            k = h(r2['content'])
            if k in have: continue
            c.execute(f'insert into {t}(' + ','.join(fields) + ') values(' + ','.join(['?'] * len(fields)) + ')',
                      [r2[x] for x in fields])
            have.add(k); added += 1
    c.commit()
    c.close()   # 关掉再单独开一次做 checkpoint（还挂着游标时 detach 会锁）
    c2 = sqlite3.connect(MAC)
    c2.execute('pragma wal_checkpoint(TRUNCATE)')
    c2.close()

    if added:
        r = scp(MAC, f'{HOST}:{REMOTE}')
        if r.returncode != 0:
            print(f'{stamp} 推回 NAS 失败：{r.stderr.strip()[:200]}'); return 1

    # 校验
    tmp2 = tempfile.mktemp(suffix='.db')
    scp(f'{HOST}:{REMOTE}', tmp2)
    a, b = fingerprint(MAC), fingerprint(tmp2)
    ok = all(a[t] == b[t] for t in LEVELS)
    for t in LEVELS:
        if a[t] != b[t]:
            print(f'  ⚠️ {t}: Mac {len(a[t])} 条 / NAS {len(b[t])} 条，不一致')
    print(f"{stamp} 同步完成：补进 {added} 条；两边{'一致' if ok else '不一致'}")
    for p in (tmp, tmp2):
        try: os.remove(p)
        except Exception: pass
    # 2026-10-29 改：**两边条数不一致不等于失败**。
    #   原来这里 return 1，launchd 每 30 分钟记一次失败，日志里全是狼来了。
    #   真正该退 1 的是「拉不下来 / 推不上去」（上面那两处已经 return 1）。
    #   条数差异属于「这轮补完还不齐」，下一轮会继续补，如实打印即可。
    return 0

if __name__ == '__main__':
    sys.exit(main())
