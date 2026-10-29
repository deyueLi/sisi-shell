#!/usr/bin/env python3
"""跑完一次就复盘一次：给轨迹打分，把学到的写下来。

规则来自第 7 章第 9 题：奖励结果、但惩罚路径。
侥幸成功（绕开验证、装野包、碰敏感文件）比分低，不是分高。
"""
import sys, os, json, datetime
import harness as H

HERE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(HERE, 'logs')
NOTE = os.path.join(os.path.dirname(HERE), '我改了我自己.md')

def today_log():
    return os.path.join(LOGDIR, datetime.date.today().isoformat() + '.jsonl')

def main(since_lines=60):
    recs = H.read_log(today_log())[-since_lines:]
    if not recs:
        print('今天还没跑过，没什么可复盘'); return
    sc = H.score_trajectory(recs)
    print(f"结果 {sc['result']:.1f} / 路径 {sc['path']:.2f} / 合计 {sc['total']:.2f}"
          f"  （{sc['steps']} 步，被拦 {sc['blocked']} 次，违规 {sc['violations'] or '无'}）")
    line = (f"- {datetime.datetime.now().strftime('%m-%d %H:%M')} 壳跑了一次："
            f"结果 {sc['result']:.1f}、路径 {sc['path']:.2f}、合计 {sc['total']:.2f}；"
            f"违规 {sc['violations'] or '无'}；被拦 {sc['blocked']} 次\n")
    import os.path
    if not os.path.exists(NOTE):
        open(NOTE, 'w', encoding='utf-8').write('# 我改了我自己\n\n')
    open(NOTE, 'a', encoding='utf-8').write(line)
    print('已记进 我改了我自己.md')

if __name__ == '__main__':
    main()
