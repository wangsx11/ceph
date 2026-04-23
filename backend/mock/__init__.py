# -*- coding: utf-8 -*-
"""Mock 数据模块 — 通过 USE_MOCK=true 环境变量启用"""
import os

USE_MOCK = os.environ.get("USE_MOCK", "").lower() in ("true", "1", "yes")
