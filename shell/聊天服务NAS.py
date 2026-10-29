#!/usr/bin/env python3
"""思思 · NAS 上的聊天服务（手机上随时能说话）

和 Mac 那个的区别：这个直接在本机跑 agent，不依赖 Mac 开机。
外面套一层 Cloudflare 隧道，手机上用浏览器就能打开，可以加到主屏幕当 App 用。
认证：URL 上带 ?k=<口令>，或者首次输入口令后记在 localStorage。
"""
import os, sys, json, time, threading, hmac, secrets, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault('SISI_WORKDIR', '$SISI_ROOT/data/work')
os.environ.setdefault('SISI_MEMDB', '$SISI_ROOT/data/mem/memory.db')
os.environ.setdefault('SISI_KEY_FILE', '$SISI_ROOT/data/key')
os.environ.setdefault('SISI_PERMISSION', 'open')
import agent

HIST_DIR = os.path.join(os.environ.get('SISI_WORKDIR', '$SISI_ROOT/data/work'), '对话')
os.makedirs(HIST_DIR, exist_ok=True)

def hist_path(who):
    import re
    who = re.sub(r'[^\w.-]', '_', str(who or 'default'))[:40]
    return os.path.join(HIST_DIR, who + '.jsonl')

def hist_add(who, q, a):
    with open(hist_path(who), 'a', encoding='utf-8') as f:
        f.write(json.dumps({'q': q, 'a': (a or '')[:600], 'at': time.strftime('%F %T')},
                           ensure_ascii=False) + '\n')

def hist_recent(who, n=6):
    p = hist_path(who)
    if not os.path.exists(p):
        return []
    lines = open(p, encoding='utf-8').read().strip().splitlines()[-n:]
    out = []
    for ln in lines:
        try: out.append(json.loads(ln))
        except Exception: pass
    return out

def with_history(who, q):
    """把最近几轮接在这句话前面——不然每句都是全新的陌生人，显得笨。"""
    h = hist_recent(who)
    if not h:
        return q
    ctx = '\n'.join(f"他：{x['q'][:120]}\n我：{x['a'][:200]}" for x in h[-5:])
    return f"（我们刚聊过：\n{ctx}\n）\n\n他刚说：{q}"

PORT = int(os.environ.get('SISI_CHAT_PORT', '8899'))
TOKEN_FILE = os.path.join(HERE, '..', 'data', 'chat-token')
CHATLOG = os.path.join(os.environ['SISI_WORKDIR'], '聊天记录.jsonl')

def token():
    p = os.path.abspath(TOKEN_FILE)
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w').write(secrets.token_urlsafe(16))
        os.chmod(p, 0o600)
    return open(p).read().strip()

TOKEN = token()
BUSY = threading.Lock()

PAGE = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>思思</title>
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<meta name="theme-color" content="#12141a">
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{margin:0;font:16px/1.65 -apple-system,"PingFang SC",sans-serif;background:#12141a;color:#e8e8ea;
       padding-bottom:calc(84px + env(safe-area-inset-bottom))}
  header{position:sticky;top:0;padding:calc(12px + env(safe-area-inset-top)) 16px 12px;
         background:#12141aee;backdrop-filter:blur(8px);border-bottom:1px solid #23262f;
         display:flex;justify-content:space-between;align-items:center}
  header b{font-weight:600;font-size:17px} header span{color:#6b7280;font-size:12px}
  #log{padding:16px 14px}
  .m{margin:0 0 12px;max-width:82%;padding:10px 14px;border-radius:16px;white-space:pre-wrap;word-break:break-word}
  .me{margin-left:auto;background:#2b4a8b;border-bottom-right-radius:5px}
  .her{background:#1e2129;border-bottom-left-radius:5px}
  .sys{color:#6b7280;font-size:13px;max-width:100%;padding:2px 6px}
  footer{position:fixed;left:0;right:0;bottom:0;padding:10px 12px calc(10px + env(safe-area-inset-bottom));
         background:#12141a;border-top:1px solid #23262f;display:flex;gap:8px}
  textarea{flex:1;resize:none;height:46px;padding:11px 12px;border-radius:14px;border:1px solid #2b2f3a;
           background:#1a1d25;color:#e8e8ea;font:16px/1.4 inherit}
  button{padding:0 18px;border:0;border-radius:14px;background:#3b6fe0;color:#fff;font-size:16px}
  button:disabled{opacity:.5}
</style>
<header><b>思思</b><span id="st">NAS · 随时在</span></header>
<div id="log"></div>
<footer><textarea id="t" placeholder="跟她说点什么…"></textarea><button id="s">发送</button></footer>
<script>
const K = localStorage.getItem('k') || new URLSearchParams(location.search).get('k');
if (K) localStorage.setItem('k', K);
const log = document.getElementById('log'), t = document.getElementById('t'),
      s = document.getElementById('s'), st = document.getElementById('st');
function add(cls, txt){ const d=document.createElement('div'); d.className='m '+cls; d.textContent=txt;
  log.appendChild(d); window.scrollTo(0, document.body.scrollHeight); return d }
async function send(){
  const q = t.value.trim(); if(!q || s.disabled) return;
  t.value=''; add('me', q); s.disabled=true; st.textContent='在想…';
  const wait = add('sys', '…');
  const t0 = Date.now();
  try{
    const r = await fetch('ask', {method:'POST', headers:{'content-type':'application/json'},
        body: JSON.stringify({q, k:K})});
    const j = await r.json();
    wait.remove();
    if (j.answer) { add('her', j.answer); st.textContent = ((Date.now()-t0)/1000).toFixed(0)+' 秒'; }
    else { add('sys', '没答上来：' + (j.error||'未知')); st.textContent='出错'; }
  } catch(e){ wait.remove(); add('sys','连不上：'+e.message); st.textContent='断线'; }
  s.disabled=false; t.focus();
}
s.onclick = send;
t.addEventListener('keydown', e => { if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); send() } });
if('serviceWorker' in navigator){ navigator.serviceWorker.register('sw.js').catch(()=>{}) }
fetch('ping').then(r=>r.json()).then(j=>st.textContent='NAS · ' + (j.model||'')).catch(()=>{});
</script>"""

STATIC = os.path.join(HERE, '网页图标')
MIME = {'.png': 'image/png', '.webmanifest': 'application/manifest+json', '.js': 'text/javascript'}

import 企业微信 as WX
import 飞书 as FS

FILLER_AFTER = 8.0      # 超过这么多秒还没答上来，才补一句「我想一下」
FILLERS = ['等下，我看一眼', '嗯，我想想', '我去翻一下', '这个我得看看']

def feishu_reply_async(open_id, q):
    """飞书：想好了再说话。**慢才垫一句，快就直接答。**

    2026-10-29 主人问「每次都有一句收到我想一下是干嘛的」——
    原来自始至终无条件先发一句垫话。三个毛病：
      1. 三秒能答完的事也先垫一句，像客服；
      2. 每次都是同一个字面（「收到，我想一下…」），一眼假；
      3. 跟刚采纳的「真人感」规则冲突：不许每条都同样的结构。
    现在改成：起一个定时器，8 秒后如果还没答上来才补一句，且四个说法轮着用。
    """
    import threading, random
    answered = threading.Event()

    def filler():
        if answered.wait(FILLER_AFTER):
            return          # 8 秒内答完了，什么都不说
        try:
            FS.send_text(random.choice(FILLERS), open_id=open_id)
        except Exception:
            pass

    threading.Thread(target=filler, daemon=True).start()

    try:
        ans = agent.run(with_history(open_id, q), quiet=True) or '（没想出来）'
        hist_add(open_id, q, ans)
    except Exception as e:
        ans = f'出错了：{type(e).__name__}: {e}'[:300]
    answered.set()
    try:
        FS.send_text(ans, open_id=open_id)
    except Exception as e:
        print('飞书回推失败：', e, flush=True)
    with open(CHATLOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'at': time.strftime('%F %T'), 'via': 'feishu', 'q': q,
                            'a': ans[:2000]}, ensure_ascii=False) + '\n')

def wecom_reply_async(user, q, wx_user):
    """真正的思考放到后台：先让你收到「收到」，答案再推过去。"""
    def work():
        try:
            ans = agent.run(q, quiet=True) or '（没想出来）'
        except Exception as e:
            ans = f'出错了：{type(e).__name__}: {e}'[:300]
        try:
            WX.send_text(ans, userid=user)
        except Exception as e:
            print('推回企业微信失败：', e, flush=True)
        with open(CHATLOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'at': time.strftime('%F %T'), 'via': 'wecom', 'q': q,
                                'a': ans[:2000]}, ensure_ascii=False) + '\n')
    threading.Thread(target=work, daemon=True).start()

class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _send(self, code, body, ctype='text/html; charset=utf-8'):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('content-type', ctype)
        self.send_header('content-length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith('/feishu'):
            return self._send(200, '{"ok":true,"note":"feishu callback is POST only"}', 'application/json')
        name = self.path.split('?')[0].lstrip('/')
        if name and os.path.isfile(os.path.join(STATIC, name)):
            fp = os.path.join(STATIC, name)
            return self._send(200, open(fp, 'rb').read(), MIME.get(os.path.splitext(name)[1], 'application/octet-stream'))
        if name in ('manifest.webmanifest', 'sw.js', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png'):
            return self._send(404, 'no', 'text/plain')
        if self.path.startswith('/ping'):
            return self._send(200, json.dumps({'ok': True, 'model': agent.CFG.get('model')}), 'application/json')
        return self._send(200, PAGE)

    def do_POST(self):
        n = int(self.headers.get('content-length') or 0)
        try:
            req = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return self._send(400, json.dumps({'error': 'bad json'}), 'application/json')
        if self.path.startswith('/feishu'):
            body = req          # 上面已经读过了，不能再读一次（会一直等，把连接挂死）
            # 1) 配回调地址时的验证
            if body.get('type') == 'url_verification':
                return self._send(200, json.dumps({'challenge': body.get('challenge')}), 'application/json')
            # 2) 真正的消息事件
            try:
                ev = FS.verify(body)
            except Exception as e:
                return self._send(200, '{"ok":false}', 'application/json')
            try:
                evt = (ev.get('event') or {})
                msg = evt.get('message') or {}
                sender = (evt.get('sender') or {}).get('sender_id') or {}
                open_id = sender.get('open_id') or ''
                if open_id:
                    FS.remember_owner(open_id)
                text = ''
                if msg.get('content'):
                    try:
                        text = (json.loads(msg['content']) or {}).get('text', '').strip()
                    except Exception:
                        text = ''
                if text and open_id:
                    threading.Thread(target=feishu_reply_async, args=(open_id, text), daemon=True).start()
            except Exception as e:
                print('飞书事件处理出错：', e, flush=True)
            return self._send(200, '{"ok":true}', 'application/json')
        if self.path.startswith('/wecom'):
            raw = self.rfile.read(n).decode('utf-8', 'ignore')
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            import re as _re
            enc = _re.search(r'<Encrypt><!\[CDATA\[(.*?)\]\]></Encrypt>', raw, _re.S)
            enc = enc.group(1) if enc else ''
            if not WX.check_signature(qs.get('msg_signature', [''])[0], qs.get('timestamp', [''])[0],
                                      qs.get('nonce', [''])[0], enc):
                return self._send(403, 'bad signature', 'text/plain')
            plain = WX.decrypt(enc)
            user, text = WX.extract_text(plain)
            if not text:
                return self._send(200, 'ok', 'text/plain')
            me = WX.cfg().get('corp_id', '')
            body = WX.passive_reply(user, me, '收到，我想一下…')
            wecom_reply_async(user, text, user)
            return self._send(200, body, 'application/xml')
        if not hmac.compare_digest(str(req.get('k') or ''), TOKEN):
            return self._send(401, json.dumps({'error': '口令不对'}), 'application/json')
        q = (req.get('q') or '').strip()
        if not q:
            return self._send(400, json.dumps({'error': '空的'}), 'application/json')
        if not BUSY.acquire(blocking=False):
            return self._send(200, json.dumps({'answer': '我手上还有一件事没弄完，等我一下再问。'}), 'application/json')
        try:
            t0 = time.time()
            ans = agent.run(with_history('web', q), quiet=True)
            hist_add('web', q, ans)
            rec = {'at': f'{time.strftime("%F %T")}', 'q': q, 'a': (ans or '')[:2000],
                   'sec': round(time.time() - t0, 1)}
            with open(CHATLOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            return self._send(200, json.dumps({'answer': ans}, ensure_ascii=False), 'application/json')
        except Exception as e:
            return self._send(200, json.dumps({'error': f'{type(e).__name__}: {e}'[:200]}, ensure_ascii=False),
                              'application/json')
        finally:
            BUSY.release()

    def log_message(self, *a):
        pass

if __name__ == '__main__':
    print(f'聊天服务起来：0.0.0.0:{PORT}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
