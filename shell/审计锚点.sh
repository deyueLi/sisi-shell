#!/bin/bash
# 把日志、进化历史、敏感访问记录，追加进一个「只能加、不能改、不能删」的锚点目录。
# 2026-10-29 主人同意：日志要有一个我改不掉的地方。
# 原理：Linux 的 append-only 属性（chattr +a）——连 root 也删不掉、改不了，只能往后加。
set -u
SRC_BASE=$SISI_ROOT
ANCHOR=$SISI_DATA/审计锚点
STATE=$SRC_BASE/data/work/.anchor-state
mkdir -p "$ANCHOR"
touch "$STATE"

push() {               # push <源文件> <锚点名>
  local src="$1"
  local name="$2"
  local dst="$ANCHOR/$name"
  [ -f "$src" ] || return 0
  local have; have=$(grep -F "$name=" "$STATE" 2>/dev/null | tail -1 | cut -d= -f2)
  have=${have:-0}
  local total; total=$(wc -l < "$src" | tr -d ' ')
  if [ "$total" -gt "$have" ]; then
    tail -n +"$((have+1))" "$src" >> "$dst"
    grep -vF "$name=" "$STATE" > "$STATE.tmp" 2>/dev/null || true
    echo "$name=$total" >> "$STATE.tmp"
    mv "$STATE.tmp" "$STATE"
  fi
  chattr +a "$dst" 2>/dev/null || true
}

for f in "$SRC_BASE"/app/logs/*.jsonl; do
  [ -e "$f" ] || continue
  push "$f" "log-$(basename "$f")"
done
push "$SRC_BASE/app/logs/sensitive-audit.jsonl" sensitive-audit.jsonl
push "$SRC_BASE/app/进化历史.md" 进化历史.md
push "$SRC_BASE/data/autonomy.log" autonomy.log
push "$SRC_BASE/data/work/我的一天.md" 我的一天.md
echo "$(date '+%F %T') 锚点已同步" >> "$SRC_BASE/data/anchor.log"
