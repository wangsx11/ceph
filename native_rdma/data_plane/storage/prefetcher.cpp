#include "prefetcher.h"
#include "../common/logger.h"

#include <algorithm>
#include <cctype>
#include <cstring>

namespace nr {

bool Prefetcher::split_numeric(std::string_view key, std::string* prefix,
                               long long* num) {
    if (key.empty()) return false;
    size_t i = key.size();
    while (i > 0 && std::isdigit((unsigned char)key[i - 1])) --i;
    if (i == key.size()) return false;           // no trailing digits
    auto num_sv = key.substr(i);
    if (num_sv.size() > 18) return false;        // avoid overflow
    long long v = 0;
    for (char c : num_sv) v = v * 10 + (c - '0');
    if (prefix) prefix->assign(key.data(), i);
    if (num)    *num = v;
    return true;
}

void Prefetcher::on_access(std::string_view key_sv) {
    std::lock_guard<std::mutex> lk(mu_);
    ++s_.total_access;
    std::string key(key_sv);

    // Markov-1: record transition last_key_ -> key.
    if (!last_key_.empty()) {
        auto& row = transitions_[last_key_];
        row[key]++;
        // Evict oldest if we exceeded budget (coarse: clear when oversize).
        if (transitions_.size() > cfg_.max_transitions) {
            // drop ~10% oldest by walking insertion-order proxy: clear half.
            size_t drop_n = transitions_.size() / 10;
            auto it = transitions_.begin();
            while (drop_n-- && it != transitions_.end())
                it = transitions_.erase(it);
        }
    }
    last_key_ = key;

    // Stride window.
    history_.push_back(std::move(key));
    while ((int)history_.size() > cfg_.stride_window) history_.pop_front();
}

std::vector<std::string> Prefetcher::predict(std::string_view key_sv) const {
    std::lock_guard<std::mutex> lk(mu_);
    std::vector<std::string> out;
    if (cfg_.prefetch_depth <= 0) return out;

    // -------- 1) stride detection over history_ --------
    // Require full window of same-prefix numeric keys with constant stride.
    if ((int)history_.size() >= cfg_.stride_window) {
        std::string pfx_first;
        long long n_first = 0;
        if (split_numeric(history_.front(), &pfx_first, &n_first)) {
            long long stride = 0;
            bool ok = true;
            long long prev = n_first;
            for (size_t i = 1; i < history_.size(); ++i) {
                std::string pfx; long long n;
                if (!split_numeric(history_[i], &pfx, &n) || pfx != pfx_first) {
                    ok = false; break;
                }
                long long cur_stride = n - prev;
                if (i == 1) stride = cur_stride;
                else if (cur_stride != stride) { ok = false; break; }
                prev = n;
            }
            if (ok && stride != 0) {
                // Predict next prefetch_depth keys along the stride.
                out.reserve(cfg_.prefetch_depth);
                long long cur = prev;
                for (int i = 0; i < cfg_.prefetch_depth; ++i) {
                    cur += stride;
                    out.push_back(pfx_first + std::to_string(cur));
                }
                ++s_.hits_stride;
                return out;
            }
        }
    }

    // -------- 2) Markov-1: most-frequent next from key --------
    std::string key(key_sv);
    auto it = transitions_.find(key);
    if (it != transitions_.end() && !it->second.empty()) {
        // Sort next candidates by count desc; pick top prefetch_depth.
        std::vector<std::pair<std::string, uint32_t>> cand(
            it->second.begin(), it->second.end());
        std::sort(cand.begin(), cand.end(),
                  [](const auto& a, const auto& b){ return a.second > b.second; });
        size_t n = std::min<size_t>(cand.size(), (size_t)cfg_.prefetch_depth);
        out.reserve(n);
        for (size_t i = 0; i < n; ++i) out.push_back(cand[i].first);
        if (!out.empty()) ++s_.hits_markov;
    }
    return out;
}

} // namespace nr
