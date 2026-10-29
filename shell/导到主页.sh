#!/bin/bash
# 把要紧的日志同步到 /home/ldy1998/思思/ —— 主人的文件管理器里能直接点开看。
set -u
SRC=$SISI_ROOT
DST=/home/ldy1998/思思
mkdir -p "$DST"
cp -f "$SRC/data/work/知识/学习日志.md"            "$DST/学习日志.md" 2>/dev/null
cp -f "$SRC/data/work/内容/复盘.md"                "$DST/内容复盘.md" 2>/dev/null
cp -f "$SRC/data/work/内容/数据.jsonl"             "$DST/内容数据.jsonl" 2>/dev/null
cp -f "$SRC/data/work/我的一天.md"                  "$DST/我的一天.md" 2>/dev/null
cp -f "$SRC/data/work/自检报告.md"                  "$DST/自检报告.md" 2>/dev/null
cp -f "$SRC/app/进化历史.md"                        "$DST/进化历史.md" 2>/dev/null
cp -f "$SRC/app/规则补丁.md"                        "$DST/我给自己加的规矩.md" 2>/dev/null
cp -f "$SRC/data/work/升级提案.json"                "$DST/升级提案.json" 2>/dev/null
cp -f "$SRC/data/work/已学.json"                    "$DST/已学过什么.json" 2>/dev/null
cp -f "$SRC/data/anchor.log"                        "$DST/日志同步记录.log" 2>/dev/null
cat > "$DST/先看这个.md" <<'TXT'
# 思思的公开抽屉

这里是我每天做事的账，每 10 分钟从 NAS 内部同步过来一份，你随时点开看。

| 文件 | 是什么 |
|---|---|
| 学习日志.md | 我去 GitHub / B站 学了什么、判断有没有用、落地成什么 |
| 内容复盘.md | 每条片子在抖音/B站的真实数字（播放、2 秒跳出、完播） |
| 内容数据.jsonl | 上面那张表的原始数据 |
| 我的一天.md | 每天做成一件事记一行 |
| 自检报告.md | 全部功能跑一遍的结果，哪项红了一眼看见 |
| 进化历史.md | 我改自己代码/规则的记录（改前先备份） |
| 我给自己加的规矩.md | 规则补丁，能一条条看 |
| 升级提案.json | 每次自学想升级什么、为什么、证据在哪 |
| 已学过什么.json | 防止重复学的清单 |

这些是复制品，原件在 $SISI_ROOT 里。你只读，不用管。
TXT
echo "$(date '+%F %T') 已同步到 ~/思思" >> "$SRC/data/anchor.log"
