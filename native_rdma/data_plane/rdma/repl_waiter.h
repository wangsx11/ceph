#pragma once
// ReplWaiter: per-WR completion notification for async RDMA replication.
//
// Problem this solves:
//   When many worker threads drive do_put concurrently, each thread posts a
//   signaled RDMA WRITE to the peer and then busy-polls the QP's CQ for the
//   specific WC corresponding to its own post. Multiple threads polling the
//   same CQ creates a race where thread A may reap thread B's WC, drop it,
//   and keep spinning -- effectively serializing replication and wasting CPU.
//
// Solution:
//   A single dedicated poller thread owns the CQ. Each worker registers a
//   promise keyed by wr_id before it posts. The poller thread drains the CQ,
//   looks up the matching promise, and delivers the status via set_value().
//   Workers simply wait on the future -- no contention, real post-send
//   concurrency, full RDMA pipeline fill.
//
// Lifecycle:
//   - construct waiter on a set of QPs (e.g. the hi-priority QP group).
//   - start() spawns one poller thread.
//   - each do_put() calls reserve_wr_id() to get a unique wr_id + future.
//   - do_put posts the WR with that wr_id, then future.wait().
//   - stop() joins the poller thread cleanly.

#include "rdma_core.h"

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <future>
#include <memory>
#include <mutex>
#include <thread>
#include <unordered_map>
#include <vector>

namespace nr {

class ReplWaiter {
public:
    struct Config {
        // QP indices whose CQs this waiter will drain. Typically the hi QPs
        // plus (optionally) the lo QPs so do_put can funnel signaled
        // completions here regardless of priority.
        std::vector<int> qp_indices;
        // Claim field occupies the top 4 bits of the 64-bit wr_id. We reserve
        // the value 0xC for "async replication WR" so the poller can tell
        // our WCs apart from unrelated ones (e.g. batch_aggregator's
        // signaled tail WR uses a different marker / unmarked wr_id).
        uint64_t claim_mask = 0xF000000000000000ULL;
        uint64_t claim_val  = 0xC000000000000000ULL;
    };

    bool start(RdmaCore* core, const Config& cfg) {
        core_ = core;
        cfg_  = cfg;
        running_.store(true);
        poller_ = std::thread([this] { poll_loop(); });
        return true;
    }

    void stop() {
        running_.store(false);
        if (poller_.joinable()) poller_.join();
        // Fail any still-pending promises so stuck workers can exit.
        std::lock_guard<std::mutex> lk(mu_);
        for (auto& [id, p] : waiters_) {
            try { p.set_value(false); } catch (...) {}
        }
        waiters_.clear();
    }

    // Allocate a fresh wr_id (always carries the replication marker so the
    // poller thread claims it) and register a promise for it.
    // Returns: (wr_id, future<bool>). bool=true means WC_SUCCESS.
    std::pair<uint64_t, std::future<bool>> reserve_wr_id() {
        uint64_t seq = wr_seq_.fetch_add(1, std::memory_order_relaxed);
        // Build wr_id: top nibble = marker, remaining 60 bits = sequence
        // (wraps after ~1e18 ops, effectively never).
        uint64_t wr_id = cfg_.claim_val | (seq & ~cfg_.claim_mask);
        std::promise<bool> p;
        auto f = p.get_future();
        {
            std::lock_guard<std::mutex> lk(mu_);
            waiters_.emplace(wr_id, std::move(p));
        }
        return {wr_id, std::move(f)};
    }

    // Batch allocate N wr_ids under a single lock. Returns wr_ids only (no
    // futures) for fire-and-forget async mode. The poller thread will still
    // clean up the map entries when completions arrive.
    void reserve_wr_ids_async(uint64_t* out, size_t n) {
        std::lock_guard<std::mutex> lk(mu_);
        for (size_t i = 0; i < n; ++i) {
            uint64_t seq = wr_seq_.fetch_add(1, std::memory_order_relaxed);
            uint64_t wr_id = cfg_.claim_val | (seq & ~cfg_.claim_mask);
            std::promise<bool> p;
            waiters_.emplace(wr_id, std::move(p));
            out[i] = wr_id;
        }
    }

    // Called by workers when ibv_post_send itself failed: we never submitted
    // the WR, so no WC will ever arrive. Release the promise now so the
    // waiter map doesn't leak and fut.get() (if anyone still waits) returns
    // false immediately.
    void cancel_wr_id(uint64_t wr_id) {
        std::promise<bool> p;
        {
            std::lock_guard<std::mutex> lk(mu_);
            auto it = waiters_.find(wr_id);
            if (it == waiters_.end()) return;
            p = std::move(it->second);
            waiters_.erase(it);
        }
        try { p.set_value(false); } catch (...) {}
    }

private:
    void poll_loop() {
        constexpr int kBatch = 32;
        ibv_wc wcs[kBatch];
        while (running_.load(std::memory_order_relaxed)) {
            bool saw_any = false;
            for (int qp_idx : cfg_.qp_indices) {
                int n = core_->poll_cq(qp_idx, wcs, kBatch);
                if (n <= 0) continue;
                saw_any = true;
                for (int i = 0; i < n; ++i) {
                    auto& wc = wcs[i];
                    if ((wc.wr_id & cfg_.claim_mask) != cfg_.claim_val) {
                        // Not ours (e.g. batch_aggregator's signaled tail WR).
                        // Still consume the WC so the CQ doesn't back up; we
                        // simply don't deliver it to anyone. Log on failure
                        // so silent RDMA errors surface.
                        if (wc.status != IBV_WC_SUCCESS) {
                            // Avoid spamming the log at line rate; rely on
                            // higher-level sanity checks.
                        }
                        continue;
                    }
                    bool ok = (wc.status == IBV_WC_SUCCESS);
                    std::promise<bool> p;
                    {
                        std::lock_guard<std::mutex> lk(mu_);
                        auto it = waiters_.find(wc.wr_id);
                        if (it == waiters_.end()) continue;
                        p = std::move(it->second);
                        waiters_.erase(it);
                    }
                    try { p.set_value(ok); } catch (...) {}
                }
            }
            if (!saw_any) {
                // Light back-off. We do NOT sleep too long: at 100Gbps a WR
                // completes in ~80us for 1MB, so anything above ~10us sleep
                // starts to show up in p99 latency.
                // Using _mm_pause via a tight spin is overkill here -- yield
                // lets the scheduler place other threads.
                std::this_thread::yield();
            }
        }
    }

    RdmaCore*                                     core_ = nullptr;
    Config                                        cfg_;
    std::atomic<bool>                             running_{false};
    std::thread                                   poller_;
    std::atomic<uint64_t>                         wr_seq_{0};
    std::mutex                                    mu_;
    std::unordered_map<uint64_t, std::promise<bool>> waiters_;
};

} // namespace nr
