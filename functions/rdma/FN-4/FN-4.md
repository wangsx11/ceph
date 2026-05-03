# FN-4 CPU 与 GPU 高速直通访问测试说明

## 功能点

记录 CPU 与 GPU 高速直通访问功能当前的硬件/环境豁免状态。

## 来源要求

`docs/功能要求.md` / RDMA 分布式仿真计算模块 / 第 4 条。

## 实现位置

- 当前未实现完整 GPU Direct RDMA 验证路径。
- 后续需要 GPU、CUDA、GPU Direct RDMA 或项目定义的等效直通路径。

## 完成判据

当前脚本直接生成 `WAIVED`，并在 `summary.md` 中说明豁免原因和后续补齐条件。

## 测试方案

前置条件：无；当前按需求文档暂时豁免。

当前验证口径：不尝试用普通 CPU 内存路径替代 GPU Direct 验收。

不验证内容：不验证 GPU 直连吞吐或延迟。

## 交互

执行 `bash functions/rdma/FN-4/run.sh`，脚本会生成 `WAIVED` 结果。

## 实现

### 当前验证口径

脚本不调用 UDS，直接输出 `WAIVED`。

### 脚本入口

- `run.sh`
- `run.py`

输出文件写入当前 `functions/rdma/FN-4/` 目录和 `logs/` 子目录。

## 命令

```bash
bash functions/rdma/FN-4/run.sh
```

