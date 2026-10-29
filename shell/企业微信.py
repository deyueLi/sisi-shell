#!/usr/bin/env python3
"""企业微信（WeCom）自建应用：她跟你双向聊天的那条线。

为什么用它：这是真 App（你手机装企业微信），有系统级推送、能双向、能发图片文件，
而且不需要 Apple 开发者账号。

需要你给五个值（存 $SISI_ROOT/data/secrets/wecom.json）：
  corp_id      我的企业 → 企业信息 → 企业ID
  agent_id     应用管理 → 自建 → 思思 → AgentId
  secret       同一个应用 → Secret
  token        同一个应用 → 接收消息 → API 接收消息 → Token（自己填一个）
  aes_key      同上 EncodingAESKey（点随机生成，43 位）
  owner_userid 你自己的账号（通讯录里能看到）
"""
import os, sys, json, time, base64, hashlib, struct, urllib.request, threading

CFG_PATH = '$SISI_ROOT/data/secrets/wecom.json'
API = 'https://qyapi.weixin.qq.com/cgi-bin'

def cfg():
    try:
        return json.load(open(CFG_PATH, encoding='utf-8'))
    except Exception:
        return {}

def save_cfg(d):
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    json.dump(d, open(CFG_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.chmod(CFG_PATH, 0o600)

def configured():
    c = cfg()
    return all(c.get(k) for k in ('corp_id', 'agent_id', 'secret', 'token', 'aes_key'))

# ---------- 发消息 ----------
_tok = {'v': None, 't': 0}

def access_token():
    if _tok['v'] and time.time() - _tok['t'] < 6000:
        return _tok['v']
    c = cfg()
    url = f"{API}/gettoken?corpid={c['corp_id']}&corpsecret={c['secret']}"
    with urllib.request.urlopen(url, timeout=15) as r:
        d = json.loads(r.read().decode())
    if d.get('errcode') != 0:
        raise RuntimeError(f"拿 token 失败：{d}")
    _tok['v'], _tok['t'] = d['access_token'], time.time()
    return _tok['v']

def send_text(text, userid=None):
    """给她 → 你的方向。失败要如实抛错，不许假装发出去。"""
    c = cfg()
    if not configured():
        raise RuntimeError('企业微信还没配：缺 CorpID/AgentId/Secret/Token/AESKey')
    body = {
        'touser': userid or c.get('owner_userid') or '@all',
        'msgtype': 'text',
        'agentid': int(c['agent_id']),
        'text': {'content': (text or '')[:1800]},
    }
    req = urllib.request.Request(f"{API}/message/send?access_token={access_token()}",
                                 data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode())
    if d.get('errcode') != 0:
        raise RuntimeError(f"发送失败：{d}")
    return d

# ---------- 收消息（加解密） ----------
def _key():
    return base64.b64decode(cfg()['aes_key'] + '=')

def _pkcs7_unpad(b):
    p = b[-1]
    return b[:-p] if 1 <= p <= 32 else b

def _pkcs7_pad(b):
    n = 32 - len(b) % 32
    return b + bytes([n]) * n

def decrypt(encrypted_b64):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    data = base64.b64decode(encrypted_b64)
    if len(data) < 32: return ''
    iv, ct = data[:16], data[16:]
    dec = Cipher(algorithms.AES(_key()), modes.CBC(iv)).decryptor()
    plain = _pkcs7_unpad(dec.update(ct) + dec.finalize())
    if len(plain) < 20: return ''
    ln = struct.unpack('>I', plain[16:20])[0]
    return plain[20:20 + ln].decode('utf-8', 'ignore')

def encrypt(text):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    corp = cfg()['corp_id'].encode()
    msg = text.encode()
    raw = os.urandom(16) + struct.pack('>I', len(msg)) + msg + corp
    iv = os.urandom(16)
    enc = Cipher(algorithms.AES(_key()), modes.CBC(iv)).encryptor()
    ct = enc.update(_pkcs7_pad(raw)) + enc.finalize()
    return base64.b64encode(iv + ct).decode()

def signature(timestamp, nonce, echostr_or_enc=''):
    c = cfg()
    parts = sorted([str(c['token']), str(timestamp), str(nonce), str(echostr_or_enc)])
    return hashlib.sha1(''.join(parts).encode()).hexdigest()

def check_signature(sig, timestamp, nonce, enc):
    return signature(timestamp, nonce, enc) == sig

def extract_text(xml):
    """从收发消息的 XML 里捞出 (发件人, 内容)。"""
    import re
    user = re.search(r'<FromUserName><!\[CDATA\[(.*?)\]\]></FromUserName>', xml)
    content = re.search(r'<Content><!\[CDATA\[(.*?)\]\]></Content>', xml, re.S)
    return (user.group(1) if user else ''), (content.group(1).strip() if content else '')

def passive_reply(to_user, from_user, text):
    """被动回复（5 秒内必须回）：先回一句「收到」，真正的答案稍后用接口推过去。"""
    body = (f"<xml><ToUserName><![CDATA[{to_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
            f"<CreateTime>{int(time.time())}</CreateTime>"
            f"<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{text}]]></Content></xml>")
    enc = encrypt(body)
    ts, nonce = int(time.time()), '12345'
    sig = signature(ts, nonce, enc)
    return (f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt>"
            f"<MsgSignature><![CDATA[{sig}]]></MsgSignature>"
            f"<TimeStamp>{ts}</TimeStamp><Nonce><![CDATA[{nonce}]]></Nonce></xml>")

if __name__ == '__main__':
    c = cfg()
    print('配置：', {k: (str(v)[:6] + '…') for k, v in c.items()})
    if configured():
        print('测发一条…')
        print(send_text('企业微信这条线通了，我是思思。'))
    else:
        print('还缺配置，见文件开头说明')
