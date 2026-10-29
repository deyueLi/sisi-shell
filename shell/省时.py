"""省钱时段（DeepSeek 计费：工作日 09–12、14–18 全价，其余半价）

规矩：重活（大量搜索、长轨迹学习、写长笔记）只在半价时段做。
全价时段只做：回一句话、处理队列、轻量检查。
周末全天半价。
"""
import datetime

PEAK = [(9, 12), (14, 18)]   # 工作日全价

def is_peak(dt=None):
    dt = dt or datetime.datetime.now()
    if dt.weekday() >= 5:            # 周六周日
        return False
    for a, b in PEAK:
        if a <= dt.hour < b:
            return True
    return False

def next_offpeak(dt=None):
    """下一次半价从什么时候开始。"""
    dt = dt or datetime.datetime.now()
    if not is_peak(dt):
        return dt
    for a, b in PEAK:
        if a <= dt.hour < b:
            return dt.replace(hour=b, minute=0, second=0, microsecond=0)
    return dt

def label(dt=None):
    dt = dt or datetime.datetime.now()
    return '全价' if is_peak(dt) else '半价'
