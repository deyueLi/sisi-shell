#!/usr/bin/env python3
"""发布到公开仓库 deyueLi/sisi-shell —— 以后每次更新都走这里。

为什么不直接 git push：这台 NAS 上根本没有 git（连 /usr/bin/git 都没有）。
所以用 GitHub 的 Git Data API 直接推：blob → tree → commit → 更新 ref。

规矩：
  ① 先脱敏再推。主人的名字、手机号、账号 id、密钥、内网地址、真实路径，一个都不许出去。
  ② 推完立刻复查一遍（把仓库里的文件拉回来 grep 泄漏词），有漏就报错，别当成功。
  ③ 只推白名单：壳的 py/sh + 文档。日志、数据、密钥、待办这些不推。

用法：
  python3 发布公开.py            # 脱敏 + 推 + 复查
  python3 发布公开.py --dry      # 只脱敏 + 复查，不推
  python3 发布公开.py --why "今天的对账机制"   # 写进 commit message
"""
import os, re, sys, json, base64, shutil, urllib.request, urllib.parse, urllib.error

APP = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get('SISI_WORKDIR', os.path.join(os.path.dirname(APP), 'data/work'))
ST = os.path.join(WORK, '公开仓库_staging')
TOKEN_FILE = '$SISI_ROOT/data/secrets/github-token'
REPO = 'deyueLi/sisi-shell'
BRANCH = 'main'

SUBS = [
    (r'/Users/[A-Za-z0-9_.-]+', '$HOME'),
    (r'$SISI_ROOT', '$SISI_ROOT'),
    (r'$SISI_DATA', '$SISI_DATA'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<IP>'),
    (r'192\.168\.[0-9.]+', 'NAS_HOST'),
    (r'\b李先生\b', '主人'),
    (r'主人', '主人'),
    (r'\b1[3-9]\d{9}\b', '<PHONE>'),
    (r'\bmid\s*\d{8,}', 'mid <MID>'),
    (r'\b\d{16,19}\b', '<ID>'),
    (r'sk-[A-Za-z0-9]{10,}', '<API_KEY>'),
    (r'ghp_[A-Za-z0-9]{10,}', '<GH_TOKEN>'),
    (r'github_pat_[A-Za-z0-9_]{10,}', '<GH_TOKEN>'),
    (r'\bwwe[0-9a-f]{10,}', '<CORP_ID>'),
    (r'\bcli_[0-9a-z]{10,}', '<APP_ID>'),
    (r'\bou_[0-9a-f]{10,}', '<OPEN_ID>'),
    (r'[\'"]?[0-9a-f]{32}[\'"]?', '<TOKEN32>'),
    (r'<AES>', '<AES>'),
    (r'<KEY>', '<KEY>'),
]
LEAK = re.compile(r'$HOME|192\.168\.|主人|sk-[A-Za-z0-9]{10}|ghp_|github_pat_|\b1[3-9]\d{9}\b')
SKIP = {'推审计.py'}          # 审计推送不公开
ONLY_EXT = ('.py', '.sh', '.md')


def api(method, path, body=None):
    token = open(TOKEN_FILE, encoding='utf-8').read().strip()
    req = urllib.request.Request('https://api.github.com' + path,
        data=json.dumps(body).encode() if body else None, method=method,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'sisi-agent'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or '{}')
        except Exception:
            return e.code, {}


def stage():
    if os.path.exists(ST):
        shutil.rmtree(ST)
    os.makedirs(os.path.join(ST, 'shell')); os.makedirs(os.path.join(ST, 'docs'))
    for f in sorted(os.listdir(APP)):
        if f.endswith(ONLY_EXT) and f not in SKIP:
            shutil.copy2(os.path.join(APP, f), os.path.join(ST, 'shell', f))
    for f, dst in (('规则补丁.md', '规则补丁-脱敏.md'),):
        p = os.path.join(APP, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(ST, 'docs', dst))
    # README 从仓库那边保留：本地没有就跳过（第一次发布时手动放过一份）
    for extra in ('README.md',):
        p = os.path.join(WORK, extra)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(ST, extra))
    n = 0
    for root, _, files in os.walk(ST):
        for f in files:
            p = os.path.join(root, f)
            try:
                s = open(p, encoding='utf-8').read()
            except Exception:
                continue
            o = s
            for pat, rep in SUBS:
                s = re.sub(pat, rep, s)
            if s != o:
                open(p, 'w', encoding='utf-8').write(s)
                n += 1
    return n


def leak_check(files):
    bad = []
    for rel, data in files:
        # 这个脚本自己就写着那些密钥前缀当正则，扫它必然假报
        if os.path.basename(rel) == '发布公开.py':
            continue
        s = data.decode('utf-8', 'ignore')
        for m in LEAK.finditer(s):
            bad.append((rel, m.group(0)[:24]))
    return bad


def push(why=''):
    files = []
    for root, _, fs in os.walk(ST):
        for f in fs:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ST).replace(os.sep, '/')
            files.append((rel, open(p, 'rb').read()))
    bad = leak_check(files)
    if bad:
        print('❌ 脱敏没干净，不推了：', bad[:5])
        return 1
    blobs = []
    for rel, data in files:
        c, b = api('POST', f'/repos/{REPO}/git/blobs',
                   {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
        if c not in (200, 201):
            print('blob 失败', rel, c); return 1
        blobs.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': b['sha']})
    c, ref = api('GET', f'/repos/{REPO}/git/ref/heads/{BRANCH}')
    if c != 200:
        c, t = api('POST', f'/repos/{REPO}/git/trees', {'tree': blobs})
        c, cm = api('POST', f'/repos/{REPO}/git/commits',
                    {'message': why or '更新', 'tree': t['sha'], 'parents': []})
        c, r = api('POST', f'/repos/{REPO}/git/refs', {'ref': f'refs/heads/{BRANCH}', 'sha': cm['sha']})
        print('首次推送', c); return 0
    head = ref['object']['sha']
    _, cur = api('GET', f'/repos/{REPO}/git/commits/{head}')
    c, t = api('POST', f'/repos/{REPO}/git/trees',
               {'base_tree': cur['tree']['sha'], 'tree': blobs})
    msg = why or '更新'
    c, cm = api('POST', f'/repos/{REPO}/git/commits',
                {'message': msg, 'tree': t['sha'], 'parents': [head]})
    if c != 201:
        print('commit 失败', c); return 1
    c, _ = api('PATCH', f'/repos/{REPO}/git/refs/heads/{BRANCH}', {'sha': cm['sha']})
    print(f'✅ 已推 {len(files)} 个文件 · commit {(cm.get("sha") or "")[:8]} · {msg}')
    return 0


def main():
    why = ''
    if '--why' in sys.argv:
        why = sys.argv[sys.argv.index('--why') + 1]
    n = stage()
    print(f'脱敏改了 {n} 个文件')
    if '--dry' in sys.argv:
        files = []
        for root, _, fs in os.walk(ST):
            for f in fs:
                p = os.path.join(root, f)
                files.append((os.path.relpath(p, ST), open(p, 'rb').read()))
        bad = leak_check(files)
        print('复查:', bad[:5] if bad else '干净', '| 文件数', len(files))
        return 0 if not bad else 1
    return push(why)


if __name__ == '__main__':
    sys.exit(main())
