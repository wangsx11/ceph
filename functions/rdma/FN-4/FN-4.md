# FN-4 CPU 与 GPU 高速直通访问测试说明

## 功能点

验证节点 A `xfusion3` 通过 RDMA WRITE/READ 直接访问节点 B `xfusion4` 上由 `cudaMalloc` 分配并注册为 RDMA MR 的 GPU buffer。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 4 条。

## 实现位置

- `native_rdma/data_plane/gpu/gpu_direct.{h,cu}`：CUDA buffer 分配、`ibv_reg_mr` 注册和 GPU 侧 pattern 校验 kernel。
- `native_rdma/data_plane/rdma/oob.{h,cpp}`：OOB 握手交换 GPU MR 的 base/len/rkey/enabled 元数据。
- `native_rdma/data_plane/main.cpp`：`RPC_GDR_STATUS`、`RPC_GDR_WRITE`、`RPC_GDR_READBACK`、`RPC_GDR_VALIDATE`。
- `functions/common/checks.py` 的 `rdma_fn4`：硬件检查、跨节点 GDR 写入、GPU kernel 校验和读回校验。

## 完成判据

满足以下全部条件才算 `PASS`：

1. `xfusion4` 存在可用 NVIDIA GPU、CUDA runtime/driver 和 CUDA 编译工具。
2. `xfusion4` 已加载 `nvidia_peermem` 或 `nv_peer_mem`。
3. `xfusion4` 数据面用 `cudaMalloc` 分配 GPU buffer，并通过 `ibv_reg_mr` 注册出有效 `lkey/rkey`。
4. `xfusion3` 数据面通过 RDMA WRITE 将 pattern 写入 `xfusion4` 的 GPU MR。
5. `xfusion4` 通过 CUDA kernel 在 GPU 侧校验 GPU buffer 内容正确，只拷回 checksum/状态标量。
6. `xfusion3` 通过 RDMA READ 从 `xfusion4` GPU MR 读回并校验 pattern 一致。

## 测试方案

前置条件：

- 当前机器可免密 `ssh xfusion4`，且节点 B `xfusion4` 已加载 `nvidia_peermem` 或 `nv_peer_mem`。
- 在节点 A 执行 `LOCAL_HOST=xfusion3 NR_GDR_ENABLE=1 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash native_rdma/start.sh`。
- `start.sh` 会让节点 A 以 `-DNR_USE_CUDA=OFF` 构建，避免 xfusion3 无 GPU/CUDA 时失败；在 `NR_GDR_ENABLE=1` 时让节点 B 以 `-DNR_USE_CUDA=ON -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc` 构建。
- 启动节点 B 时传入 `NR_GDR_ENABLE=1 NR_CUDA_DEVICE=0 NR_GDR_BYTES=67108864`，由 B 暴露 64MiB GPU MR。

当前验证口径：

- CPU 只负责准备源端测试 pattern 并提交 RDMA WR。
- 数据 payload 由 RNIC 直接写入远端 GPU 显存。
- 不使用普通 CPU slab、TCP、全量 `cudaMemcpy` payload 或脚本写 JSON 冒充 GPU Direct。
- 不统计 GPU Direct 吞吐或延迟性能阈值。

## 交互

执行：

```bash
ssh xfusion4 'hostname; nvidia-smi; nvidia-smi topo -m; lsmod | egrep "nvidia_peermem|nv_peer_mem"; /usr/local/cuda/bin/nvcc --version || nvcc --version || true; ibv_devinfo | head -80'

cd native_rdma
LOCAL_HOST=xfusion3 NR_GDR_ENABLE=1 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh
cd ..
REQUIRE_PEER=1 bash functions/rdma/FN-4/run.sh
```

如果 peer memory 模块未加载，需要先在 `xfusion4` 上手动执行 `sudo modprobe nvidia-peermem`，不要在脚本里用 CPU buffer 或 TCP 路径降级后标记 `PASS`。

## 实现

### 当前验证口径

脚本直连节点 A 的 C++ 数据面 UDS，调用 `RPC_GDR_STATUS`、`RPC_GDR_WRITE`、`RPC_GDR_READBACK`；同时通过 `ssh xfusion4` 调用节点 B 本地 UDS 的 `RPC_GDR_STATUS`、`RPC_GDR_VALIDATE`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-4/` 目录和 `logs/` 子目录。

## 命令

完整启动加验收：

```bash
cd native_rdma
LOCAL_HOST=xfusion3 NR_GDR_ENABLE=1 NR_TRANSPORT=rdma NR_ASYNC_REPL=0 bash start.sh
cd ..
REQUIRE_PEER=1 bash functions/rdma/FN-4/run.sh
```

若双节点数据面已按 GDR 模式在线，仅重跑 FN-4：

```bash
REQUIRE_PEER=1 bash functions/rdma/FN-4/run.sh
```
