#!/bin/bash
# 手机入口：把 NAS 上的聊天服务通过 Cloudflare 隧道露到公网。
# 每次重启网址会变，所以把当前网址写进 /home/ldy1998/思思/手机入口.md，随时能查到最新的。
set -u
unset GODEBUG GOFLAGS 2>/dev/null
LOG=$SISI_ROOT/data/tunnel.log
ENTRY=/home/ldy1998/思思/手机入口.md
TOKEN=$(cat $SISI_ROOT/data/chat-token 2>/dev/null)
: > "$LOG"
$SISI_ROOT/bin/cloudflared tunnel --url http://127.0.0.1:8899 --no-autoupdate >> "$LOG" 2>&1 &
CF=$!
for i in $(seq 1 60); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1)
  [ -n "${URL:-}" ] && break
  sleep 2
done
if [ -n "${URL:-}" ]; then
  mkdir -p "$(dirname "$ENTRY")"
  cat > "$ENTRY" <<TXT
# 手机入口（$(date '+%F %T')）

用 iPhone 的 Safari 打开这个地址（带口令，别外传）：

$URL/?k=$TOKEN

## 当 App 用（推荐）

1. Safari 打开上面那个网址
2. 点底部「分享」→「添加到主屏幕」→ 添加
3. 桌面上就有「思思」图标了，点开是全屏的，没有地址栏

## 想要更像 App：装个快捷指令

用 Safari 打开：$URL/sisi.shortcut

装好后桌面上是「思思」，点一下直接问、直接看回答。还可以对着它说：
「嘿 Siri，思思」——不用解锁就能问。

（第一次装可能要先打开一次「快捷指令」App，并在
 设置 → 快捷指令 → 打开「允许不受信任的快捷指令」）

## 她主动找你

她会通过微信给你发消息（Mac 开着的时候）。网址重启会变，变了这里会自动更新。
TXT
  echo "入口：$URL/?k=$TOKEN"
else
  echo "没拿到网址，看 $LOG"
fi
wait $CF
