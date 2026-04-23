# -*- coding: utf-8 -*-
"""工具函数与公共常量"""
import hashlib
import random
from datetime import datetime


def ts():
    """当前时间戳 HH:MM:SS"""
    return datetime.now().strftime('%H:%M:%S')


def compute_hash(data):
    """计算数据哈希(前8位)"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.md5(data).hexdigest()[:8]


def get_obj_size(data):
    """获取友好大小"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    size = len(data)
    if size < 1024:
        return f"{size}B"
    return f"{size/1024:.1f}KB"


# 军事化命名
MIL_NAMES = [
    "兵力部署", "侦察情报", "装备清单", "作战计划", "通信记录",
    "弹药储备", "后勤物资", "战术指令", "敌情研判", "防空部署",
    "火力配置", "工事构筑", "指挥通联", "卫勤保障", "测绘数据",
    "预警信息", "电子对抗", "频谱管控", "气象数据", "航线规划",
    "阵地编成", "战斗编组", "补给路线", "伤亡统计", "战场态势",
    "雷达数据", "光电侦察", "无人机航迹", "炮兵诸元", "防化信息",
]


def mil_name(idx=None):
    if idx is None:
        idx = random.randint(0, len(MIL_NAMES) - 1)
    name = MIL_NAMES[idx % len(MIL_NAMES)]
    suffix = f"_{chr(65 + random.randint(0, 25))}{random.randint(1, 99):02d}"
    return name + suffix
