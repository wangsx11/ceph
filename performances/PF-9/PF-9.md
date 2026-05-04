# PF-9 仿真引擎内存池化能力测试说明

## 功能点

- 性能点名称：仿真引擎内存池化能力。
- 来源指标：`docs/性能要求.md` 第 9 条。
- 现有参考脚本：`native_rdma/tests/performance/perf_09_mempool.sh`。
- 功能说明：验证内存池化在性能损失受控前提下的内存节省能力，以及单节点多线程分配释放吞吐提升。

## 指标要求

- 默认对象大小：1KB。
- 场景一：启用内存池后的性能损失 `overhead_pct <= 5%`，内存节省 `savings_pct >= 7%`。
- 场景二：单节点多线程高并发 1KB 对象分配/释放吞吐提升 `scale_gain_pct >= 20%`。
- 需要报告线程数、总操作数、基线吞吐、内存池吞吐、性能损失、内存节省和扩展收益。

## 测试方案

- 数据面 `nr::SlabPool` 使用固定大小 slot、RDMA MR 注册内存和线程本地批量缓存，热路径 `alloc/free` 优先走本地 cache，cache 不足时再批量访问全局 free list。
- benchmark 的 slab 路径采用与生产 SlabPool 相同的线程本地批量缓存模型，用于隔离测量 allocator 本身的开销。
- 执行 warmup 轮次，丢弃 warmup 统计。
- 场景一对比启用内存池前后的性能和内存占用；内存占用通过独立子进程在对象仍然存活时读取 RSS，避免场景之间互相污染。
- 场景二在单节点多线程下对比 1KB 对象分配/释放/初始化吞吐，计算吞吐提升比例。吞吐基线只包含 16B 轻量对象头，避免把未池化路径建模得过重。

## 交互

1. 构建数据面或单元 bench：
   ```bash
   cd native_rdma
   cmake --build build -j
   ```
2. 设置可选参数：
   ```bash
   export THREADS=8
   export OBJECT_SIZE=1024
   export MEASURED_RUNS=3
   ```
3. 执行脚本：
   ```bash
   cd performances/PF-9
   bash run.sh
   ```
4. 查看结果：读取当前目录下的 `summary.md`，原始对比数据固定写入当前目录。

## 实现

### 当前统计口径

- `overhead_pct = max((baseline_ops - pool_ops) / baseline_ops * 100%, 0)`，即 slab 比 malloc 慢多少；slab 更快时记为 `0`，表示无性能损失。
- `savings_pct = (malloc_live_rss_kb - slab_live_rss_kb) / malloc_live_rss_kb * 100%`。
- `scale_gain_pct = (pool_alloc_free_ops - baseline_alloc_free_ops) / baseline_alloc_free_ops * 100%`。
- 统计 measured 测试窗口，不统计构建、脚本启动、环境启动和 warmup 时间。
- 吞吐测试中，malloc 和 slab 都会在分配后真实初始化完整 1KB 对象；malloc 基线额外携带 16B 轻量对象头。
- 内存节省测试的基线是未池化 RDMA 对象记录：每个对象包含 1KB payload 和 128B 对象/MR 元数据；slab 场景把 1KB payload 密集放入固定 slot，并用紧凑 free list 管理。
- 不使用固定节省率 fallback；如果 live RSS 不能真实达到 7% 节省，PF-9 直接失败。

### 脚本入口

- Bash 入口：`performances/PF-9/run.sh`。
- Python 入口：`performances/PF-9/run.py`。
- 本次运行结果直接写入当前 `performances/PF-9/` 目录。

## 命令

```bash
cd performances/PF-9
bash run.sh
```
