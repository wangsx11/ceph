#include "io_scheduler.h"
#include "../common/logger.h"

#include <atomic>
#include <mutex>
#include <thread>
#include <unordered_map>
#include <vector>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/types.h>

#ifdef NR_USE_IO_URING
#include <liburing.h>
#endif

namespace nr {

namespace {

struct RingCtx {
#ifdef NR_USE_IO_URING
    io_uring           ring{};
    bool               inited = false;
#endif
    int                fd     = -1;
    std::string        path;
    std::mutex         submit_mu;
    std::thread        completer;
    std::atomic<bool>  stop{false};

    // wr_id -> callback
    std::mutex                                           cb_mu;
    std::unordered_map<uint64_t, IoScheduler::OnDone>    cbs;
    std::atomic<uint64_t>                                next_id{1};
    std::atomic<uint64_t>                                read_ops{0};
    std::atomic<uint64_t>                                write_ops{0};
    std::atomic<uint64_t>                                read_bytes{0};
    std::atomic<uint64_t>                                write_bytes{0};
};

} // namespace

struct IoSchedulerImpl {
    RingCtx fg;
    RingCtx bg;
    int     sq_depth = 1024;
};

static IoSchedulerImpl* g_impl = nullptr;

static int open_backing_file(const std::string& raw_path, off_t pre_size) {
    // 兼容性：部署脚本（demo_up.sh）可能把 NVME_PATH/HDD_PATH 作为"冷热层
    // 目录"预先 mkdir 了出来。历史 DP 代码直接 open(path, O_RDWR|O_CREAT)，
    // 若 path 指向已存在目录会 fail errno=EISDIR，tier I/O 全部退化为 -EBADF。
    // 这里检测：如果 path 是目录，就在里面追加文件名 "tier.bin" 作为真正的
    // backing file；否则沿用原 path 语义。
    std::string path = raw_path;
    struct stat dst{};
    if (::stat(raw_path.c_str(), &dst) == 0 && S_ISDIR(dst.st_mode)) {
        if (!path.empty() && path.back() != '/') path.push_back('/');
        path += "tier.bin";
        NR_INFO("io_scheduler: %s is a directory, using backing file %s",
                raw_path.c_str(), path.c_str());
    }
    int fd = ::open(path.c_str(), O_RDWR | O_CREAT, 0644);
    if (fd < 0) {
        NR_WARN("io_scheduler: open(%s) failed errno=%d (%s)",
                path.c_str(), errno, std::strerror(errno));
        return -1;
    }
    // Pre-grow so offset-based writes don't fail on fresh files.
    struct stat st{};
    if (::fstat(fd, &st) == 0 && st.st_size < pre_size) {
        if (::ftruncate(fd, pre_size) < 0) {
            NR_WARN("io_scheduler: ftruncate(%s, %ld) failed errno=%d",
                    path.c_str(), (long)pre_size, errno);
        }
    }
    NR_INFO("io_scheduler: backing file %s ready (fd=%d size>=%lld)",
            path.c_str(), fd, (long long)pre_size);
    return fd;
}

#ifdef NR_USE_IO_URING
static void completer_loop(RingCtx* rc) {
    while (!rc->stop.load(std::memory_order_relaxed)) {
        io_uring_cqe* cqe = nullptr;
        // Wait up to 50ms so we can observe the stop flag.
        __kernel_timespec ts{0, 50'000'000};
        int r = io_uring_wait_cqe_timeout(&rc->ring, &cqe, &ts);
        if (r == -ETIME || r == -EINTR) continue;
        if (r < 0 || !cqe) continue;

        uint64_t wr_id = (uint64_t)io_uring_cqe_get_data(cqe);
        int      res   = cqe->res;
        io_uring_cqe_seen(&rc->ring, cqe);

        IoScheduler::OnDone cb;
        {
            std::lock_guard<std::mutex> lk(rc->cb_mu);
            auto it = rc->cbs.find(wr_id);
            if (it != rc->cbs.end()) { cb = std::move(it->second); rc->cbs.erase(it); }
        }
        if (cb) cb(res);
    }
}
#endif

bool IoScheduler::init(const Config& cfg) {
    if (g_impl) { NR_WARN("IoScheduler already inited"); return true; }
    g_impl = new IoSchedulerImpl();
    g_impl->sq_depth = cfg.sq_depth > 0 ? cfg.sq_depth : 1024;

    // Pre-size each backing file to 1 GiB; actual storage grows sparsely
    // (tmpfs / ext4 support sparse files so disk usage tracks real writes).
    const off_t kPreSize = 1LL << 30;

    g_impl->fg.path = cfg.fg_path;
    g_impl->bg.path = cfg.bg_path;
    g_impl->fg.fd   = open_backing_file(cfg.fg_path, kPreSize);
    g_impl->bg.fd   = open_backing_file(cfg.bg_path, kPreSize);

#ifdef NR_USE_IO_URING
    auto bring_up = [&](RingCtx& rc, bool /*sqpoll*/) -> bool {
        unsigned flags = 0; // SQPOLL needs CAP_SYS_NICE; keep default for demo
        if (io_uring_queue_init(g_impl->sq_depth, &rc.ring, flags) < 0) {
            NR_WARN("io_scheduler: io_uring_queue_init failed on %s", rc.path.c_str());
            return false;
        }
        rc.inited = true;
        rc.completer = std::thread(completer_loop, &rc);
        return true;
    };
    bring_up(g_impl->fg, cfg.sq_poll_fg);
    bring_up(g_impl->bg, false);
#endif

    NR_INFO("IoScheduler init fg=%s (fd=%d) bg=%s (fd=%d) sq_depth=%d",
            cfg.fg_path.c_str(), g_impl->fg.fd,
            cfg.bg_path.c_str(), g_impl->bg.fd,
            g_impl->sq_depth);
    return true;
}

void IoScheduler::shutdown() {
    if (!g_impl) return;
#ifdef NR_USE_IO_URING
    auto stop_ring = [](RingCtx& rc) {
        if (!rc.inited) return;
        rc.stop.store(true);
        if (rc.completer.joinable()) rc.completer.join();
        io_uring_queue_exit(&rc.ring);
        rc.inited = false;
    };
    stop_ring(g_impl->fg);
    stop_ring(g_impl->bg);
#endif
    if (g_impl->fg.fd >= 0) ::close(g_impl->fg.fd);
    if (g_impl->bg.fd >= 0) ::close(g_impl->bg.fd);
    delete g_impl;
    g_impl = nullptr;
}

static RingCtx* pick(IoScheduler::Prio p) {
    if (!g_impl) return nullptr;
    return p == IoScheduler::Prio::FG ? &g_impl->fg : &g_impl->bg;
}

static void account_read(RingCtx* rc, int rc_val) {
    if (!rc || rc_val <= 0) return;
    rc->read_ops.fetch_add(1, std::memory_order_relaxed);
    rc->read_bytes.fetch_add((uint64_t)rc_val, std::memory_order_relaxed);
}

static void account_write(RingCtx* rc, int rc_val) {
    if (!rc || rc_val <= 0) return;
    rc->write_ops.fetch_add(1, std::memory_order_relaxed);
    rc->write_bytes.fetch_add((uint64_t)rc_val, std::memory_order_relaxed);
}

int IoScheduler::async_write(Prio p, const void* buf, size_t len,
                             uint64_t offset, OnDone cb) {
    RingCtx* rc = pick(p);
    if (!rc || rc->fd < 0) { if (cb) cb(-EBADF); return -EBADF; }

#ifdef NR_USE_IO_URING
    if (rc->inited) {
        uint64_t id = rc->next_id.fetch_add(1, std::memory_order_relaxed);
        {
            std::lock_guard<std::mutex> lk(rc->cb_mu);
            if (cb) rc->cbs.emplace(id, std::move(cb));
        }
        std::lock_guard<std::mutex> lk(rc->submit_mu);
        io_uring_sqe* sqe = io_uring_get_sqe(&rc->ring);
        if (!sqe) {
            std::lock_guard<std::mutex> lk2(rc->cb_mu);
            auto it = rc->cbs.find(id);
            if (it != rc->cbs.end()) { auto c = std::move(it->second); rc->cbs.erase(it);
                if (c) c(-EAGAIN); }
            return -EAGAIN;
        }
        io_uring_prep_write(sqe, rc->fd, buf, (unsigned)len, offset);
        io_uring_sqe_set_data(sqe, (void*)id);
        int submitted = io_uring_submit(&rc->ring);
        if (submitted > 0) {
            rc->write_ops.fetch_add(1, std::memory_order_relaxed);
            rc->write_bytes.fetch_add(len, std::memory_order_relaxed);
        }
        return submitted;
    }
#endif
    // Fallback: sync pwrite.
    ssize_t r = ::pwrite(rc->fd, buf, len, offset);
    int rc_val = (r < 0) ? -errno : (int)r;
    account_write(rc, rc_val);
    if (cb) cb(rc_val);
    return rc_val;
}

int IoScheduler::async_read(Prio p, void* buf, size_t len,
                            uint64_t offset, OnDone cb) {
    RingCtx* rc = pick(p);
    if (!rc || rc->fd < 0) { if (cb) cb(-EBADF); return -EBADF; }

#ifdef NR_USE_IO_URING
    if (rc->inited) {
        uint64_t id = rc->next_id.fetch_add(1, std::memory_order_relaxed);
        {
            std::lock_guard<std::mutex> lk(rc->cb_mu);
            if (cb) rc->cbs.emplace(id, std::move(cb));
        }
        std::lock_guard<std::mutex> lk(rc->submit_mu);
        io_uring_sqe* sqe = io_uring_get_sqe(&rc->ring);
        if (!sqe) {
            std::lock_guard<std::mutex> lk2(rc->cb_mu);
            auto it = rc->cbs.find(id);
            if (it != rc->cbs.end()) { auto c = std::move(it->second); rc->cbs.erase(it);
                if (c) c(-EAGAIN); }
            return -EAGAIN;
        }
        io_uring_prep_read(sqe, rc->fd, buf, (unsigned)len, offset);
        io_uring_sqe_set_data(sqe, (void*)id);
        int submitted = io_uring_submit(&rc->ring);
        if (submitted > 0) {
            rc->read_ops.fetch_add(1, std::memory_order_relaxed);
            rc->read_bytes.fetch_add(len, std::memory_order_relaxed);
        }
        return submitted;
    }
#endif
    ssize_t r = ::pread(rc->fd, buf, len, offset);
    int rc_val = (r < 0) ? -errno : (int)r;
    account_read(rc, rc_val);
    if (cb) cb(rc_val);
    return rc_val;
}

int IoScheduler::sync_write(Prio p, const void* buf, size_t len, uint64_t offset) {
    RingCtx* rc = pick(p);
    if (!rc || rc->fd < 0) return -EBADF;
    ssize_t r = ::pwrite(rc->fd, buf, len, offset);
    int rc_val = (r < 0) ? -errno : (int)r;
    account_write(rc, rc_val);
    return rc_val;
}

int IoScheduler::sync_read(Prio p, void* buf, size_t len, uint64_t offset) {
    RingCtx* rc = pick(p);
    if (!rc || rc->fd < 0) return -EBADF;
    ssize_t r = ::pread(rc->fd, buf, len, offset);
    int rc_val = (r < 0) ? -errno : (int)r;
    account_read(rc, rc_val);
    return rc_val;
}

IoScheduler::Stats IoScheduler::stats() const {
    Stats s;
    if (!g_impl) return s;
    s.fg_read_ops = g_impl->fg.read_ops.load(std::memory_order_relaxed);
    s.fg_write_ops = g_impl->fg.write_ops.load(std::memory_order_relaxed);
    s.fg_read_bytes = g_impl->fg.read_bytes.load(std::memory_order_relaxed);
    s.fg_write_bytes = g_impl->fg.write_bytes.load(std::memory_order_relaxed);
    s.bg_read_ops = g_impl->bg.read_ops.load(std::memory_order_relaxed);
    s.bg_write_ops = g_impl->bg.write_ops.load(std::memory_order_relaxed);
    s.bg_read_bytes = g_impl->bg.read_bytes.load(std::memory_order_relaxed);
    s.bg_write_bytes = g_impl->bg.write_bytes.load(std::memory_order_relaxed);
    return s;
}

} // namespace nr
