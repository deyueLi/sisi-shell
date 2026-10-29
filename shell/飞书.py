#!/usr/bin/env python3
"""飞书（Lark）自建应用：跟她双向聊天的那条线。

为什么选飞书：它的自建应用对回调地址比企业微信宽松，而且机器人 API 国内直连。
需要两样（存 $SISI_ROOT/data/secrets/feishu.json）：
  app_id / app_secret    开放平台 → 凭证与基础信息
可选：
  token / encrypt_key    事件订阅里的 Verification Token / Encrypt Key
  owner_open_id          你自己的 open_id（第一次发消息时自动记下来）
"""
import os, json, time, base64, hashlib, struct, urllib.request

CFG = '$SISI_ROOT/data/secrets/feishu.json'
BASE = 'https://open.feishu.cn/open-apis'

def cfg():
    try: return json.load(open(CFG, encoding='utf-8'))
    except Exception: return {}

def save(d):
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    json.dump(d, open(CFG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.chmod(CFG, 0o600)

def configured():
    c = cfg()
    return bool(c.get('app_id') and c.get('app_secret'))

_tok = {'v': None, 't': 0}

def token():
    if _tok['v'] and time.time() - _tok['t'] < 1500:
        return _tok['v']
    c = cfg()
    body = json.dumps({'app_id': c['app_id'], 'app_secret': c['app_secret']}).encode()
    req = urllib.request.Request(BASE + '/auth/v3/tenant_access_token/internal', data=body,
                                 headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode())
    if d.get('code') != 0:
        raise RuntimeError(f"拿 token 失败：{d}")
    _tok['v'], _tok['t'] = d['tenant_access_token'], time.time()
    return _tok['v']

def _post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={'content-type': 'application/json',
                                          'Authorization': 'Bearer ' + token()})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def _chunks(text, limit=2800):
    """按句子边界切块。**绝不截断**——超过上限就分多条发（2026-10-29 修的：
    原来单条写死 text[:3000]，主人那边只看到半句话，聊天看起来就不连贯、缺东西）。"""
    text = text or ''
    if len(text) <= limit:
        return [text]
    import re
    parts, buf = [], ''
    for seg in re.split(r'(?<=[。！？\n])', text):
        if len(buf) + len(seg) > limit and buf:
            parts.append(buf)
            buf = seg
        else:
            buf += seg
    if buf:
        parts.append(buf)
    # 极端情况：一整段没有句号，硬切
    out = []
    for p in parts:
        while len(p) > limit:
            out.append(p[:limit]); p = p[limit:]
        if p:
            out.append(p)
    return out


def send_text(text, open_id=None, chat_id=None):
    """她 → 你。长文自动分条发，按顺序。失败要如实抛错。"""
    c = cfg()
    rid = open_id or c.get('owner_open_id')
    if not chat_id and not rid:
        raise RuntimeError('还不知道你的 open_id：先在飞书里给机器人发一句话，我就记住了')
    parts = _chunks(text)
    last = None
    for i, part in enumerate(parts, 1):
        body_txt = part if len(parts) == 1 else f'({i}/{len(parts)})\n{part}'
        body = {'receive_id': chat_id or rid, 'msg_type': 'text',
                'content': json.dumps({'text': body_txt}, ensure_ascii=False)}
        kind = 'chat_id' if chat_id else 'open_id'
        d = _post(f'/im/v1/messages?receive_id_type={kind}', body)
        if d.get('code') != 0:
            raise RuntimeError(f"发送失败（第 {i}/{len(parts)} 段）：{d.get('code')} {d.get('msg')}")
        last = d
        import time as _t
        if len(parts) > 1:
            _t.sleep(0.35)   # 段间留一点，别让飞书排序错乱
    return last


def remember_owner(open_id):
    if not open_id: return
    c = cfg(); c['owner_open_id'] = open_id; save(c)

# ---------- 事件订阅（版本 2.0 回调） ----------
def decrypt(encrypt_b64):
    """飞书事件加密：AES-256-CBC，key = sha256(encrypt_key)，前 16 字节 IV。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    key = hashlib.sha256(cfg()['encrypt_key'].encode()).digest()
    raw = base64.b64decode(encrypt_b64)
    iv, ct = raw[:16], raw[16:]
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    pad = d.update(ct) + d.finalize()
    p = pad[-1]
    return pad[:-p].decode('utf-8', 'ignore')

def verify(body):
    """事件回调里可能带 encrypt 字段，先解开再判断是不是 url_verification。"""
    enc = body.get('encrypt')
    if enc:
        try:
            return json.loads(decrypt(enc))
        except Exception as e:
            raise RuntimeError(f'解密失败：{e}')
    return body
