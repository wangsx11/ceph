## 尝试 1 — 2026-04-25 16:00

### 修改内容
已为测试公共 RADOS 连接增加逻辑 pool 到 `testbench` namespace 的 fallback，并回跑 `test_03_qos_priority.py`。

### 测试输出
```text
Traceback (most recent call last):
  File "test_03_qos_priority.py", line 82, in <module>
    main()
  File "test_03_qos_priority.py", line 46, in main
    ioctx_l = cluster.open_ioctx(POOL)
  File "rados.pyx", line 998, in rados.Rados.open_ioctx
rados.ObjectNotFound: [errno 2] RADOS object not found (error opening pool 'test_qos_pool')
Error in sys.excepthook:
Traceback (most recent call last):
  File "/usr/lib/python3/dist-packages/apport_python_hook.py", line 72, in apport_excepthook
    from apport.fileutils import likely_packaged, get_recent_crashes
  File "/usr/lib/python3/dist-packages/apport/__init__.py", line 5, in <module>
    from apport.report import Report
  File "/usr/lib/python3/dist-packages/apport/report.py", line 32, in <module>
    import apport.fileutils
  File "/usr/lib/python3/dist-packages/apport/fileutils.py", line 12, in <module>
    import os, glob, subprocess, os.path, time, pwd, sys, requests_unixsocket
  File "/usr/lib/python3/dist-packages/requests_unixsocket/__init__.py", line 1, in <module>
    import requests
  File "/usr/lib/python3/dist-packages/requests/__init__.py", line 95, in <module>
    from urllib3.contrib import pyopenssl
  File "/usr/lib/python3/dist-packages/urllib3/contrib/pyopenssl.py", line 46, in <module>
    import OpenSSL.SSL
  File "/usr/lib/python3/dist-packages/OpenSSL/__init__.py", line 8, in <module>
    from OpenSSL import crypto, SSL
  File "/usr/lib/python3/dist-packages/OpenSSL/crypto.py", line 1553, in <module>
    class X509StoreFlags(object):
  File "/usr/lib/python3/dist-packages/OpenSSL/crypto.py", line 1571, in X509StoreFlags
    NOTIFY_POLICY = _lib.X509_V_FLAG_NOTIFY_POLICY
AttributeError: module 'lib' has no attribute 'X509_V_FLAG_NOTIFY_POLICY'

Original exception was:
Traceback (most recent call last):
  File "test_03_qos_priority.py", line 82, in <module>
    main()
  File "test_03_qos_priority.py", line 46, in main
    ioctx_l = cluster.open_ioctx(POOL)
  File "rados.pyx", line 998, in rados.Rados.open_ioctx
rados.ObjectNotFound: [errno 2] RADOS object not found (error opening pool 'test_qos_pool')
```

### 失败原因分析
`rados_pool(POOL)` 已经 fallback 到 `testbench` 并设置 namespace，但测试内部第二个 low-priority ioctx 直接调用 `cluster.open_ioctx(POOL)`，因此仍尝试打开不存在的物理 pool `test_qos_pool`。

## 尝试 2 — 2026-04-25 16:01

### 修改内容
新增 `open_ioctx(cluster, pool)` helper，使 `test_03_qos_priority.py` 的第二个 ioctx 也使用同一 fallback 规则。

### 测试输出
```text
[INFO] throughput H=15222 ops/s  L=13999 ops/s  gain=8.7%
[FAIL] high-priority gain: 8.74% < 22.0% (target NOT met)
```

### 失败原因分析
low-priority 分支在提交期间短暂 sleep，但仍一次性累计大量异步请求后统一等待，实际效果接近 high-priority 队列，没有形成足够的节流差异。

## 尝试 3 — 2026-04-25 16:03

### 修改内容
回跑 `test_05_routing_lb.py`，使用公共 RADOS fallback 消除了并发线程中的 pool 创建错误。

### 测试输出
```text
[INFO] OSD kb_used sample: [3995896, 4389788, 5632084]
[INFO] OSD kb_used sample: [4009020, 4390028, 5632084]
[INFO] growth kb per OSD: [13124, 240, 0];  hosts active=2;  worst deviation=96.4%
[ OK ] active OSD hosts: 2.00 >= 2
[FAIL] max deviation: 96.41% > 30% (target NOT met)
```

### 失败原因分析
`kb_used` 是 OSD 存储占用的异步统计，不等价于本轮写入的路由分布。BlueStore 分配、压缩、后台回收和采样时序会让即时容量差值严重偏斜。

## 尝试 4 — 2026-04-25 16:05

### 修改内容
将 `test_05_routing_lb.py` 改为对写入对象采样 `ceph osd map` 的 acting set。

### 测试输出
```text
测试长时间停留在多次 `ceph osd map ... -f json` 调用，未在合理时间内完成；手动终止进程。
```

### 失败原因分析
每个 `ceph osd map` 都会启动一次 Ceph CLI 并连接 monitor，256 次采样在当前 RDMA 配置下开销过大。应改为一次性读取 CRUSH/OSD tree 配置来判断 pool 的可均衡主机集合。
