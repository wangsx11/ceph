#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RDMA 网络诊断脚本：读取 ibstat / show_gids / ibdev2netdev，输出当前
RoCE / IB 端口列表、速率、MTU 与活跃状态。

主要作为环境检查，不产生 pass/fail。
"""
import os
import subprocess
import sys


def main():
    cmds = [
        "ibstat",
        "ibdev2netdev -v",
        "show_gids 2>/dev/null || true",
        "cat /sys/module/rdma_rxe/parameters/* 2>/dev/null || true",
        "ceph config get global ms_type",
        "ceph config dump | grep -E 'rdma|ms_'",
    ]
    for c in cmds:
        print(f"---- $ {c} ----")
        subprocess.call(c, shell=True)


if __name__ == "__main__":
    main()
