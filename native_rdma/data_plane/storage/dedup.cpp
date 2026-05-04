#include "dedup.h"
#include <openssl/sha.h>
#include <cstring>

namespace nr {

uint64_t Dedup::fingerprint(std::string_view data) {
    uint8_t md[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const uint8_t*>(data.data()), data.size(), md);
    uint64_t fp = 0;
    std::memcpy(&fp, md, sizeof(fp));
    return fp;
}

uint64_t Dedup::observe(const std::string& data, bool* duplicate) {
    uint64_t fp = fingerprint(data);
    std::lock_guard<std::mutex> lk(mu_);
    auto it = refs_.find(fp);
    if (it == refs_.end()) {
        Entry e;
        e.raw_size = (uint32_t)data.size();
        e.stored_size = (uint32_t)data.size();
        e.refs = 1;
        refs_[fp] = e;
        logical_bytes_ += data.size();
        if (duplicate) *duplicate = false;
    } else {
        it->second.refs++;
        duplicate_objects_++;
        saved_bytes_ += data.size();
        logical_bytes_ += data.size();
        if (duplicate) *duplicate = true;
    }
    return fp;
}

bool Dedup::lookup(uint64_t fp, Entry* out) const {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = refs_.find(fp);
    if (it == refs_.end()) return false;
    if (out) *out = it->second;
    return true;
}

bool Dedup::retain_or_insert(uint64_t fp, uint64_t offset, uint32_t raw_size,
                             uint32_t stored_size, uint8_t algo, Entry* out,
                             bool* duplicate) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = refs_.find(fp);
    if (it == refs_.end()) {
        Entry e;
        e.offset = offset;
        e.raw_size = raw_size;
        e.stored_size = stored_size;
        e.algo = algo;
        e.refs = 1;
        refs_[fp] = e;
        logical_bytes_ += raw_size;
        if (out) *out = e;
        if (duplicate) *duplicate = false;
        return true;
    }
    it->second.refs++;
    duplicate_objects_++;
    saved_bytes_ += stored_size;
    logical_bytes_ += raw_size;
    if (out) *out = it->second;
    if (duplicate) *duplicate = true;
    return true;
}

void Dedup::release(uint64_t fp) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = refs_.find(fp);
    if (it == refs_.end()) return;
    if (it->second.refs > 0) it->second.refs--;
    if (it->second.refs == 0) refs_.erase(it);
}

Dedup::Stats Dedup::stats() const {
    std::lock_guard<std::mutex> lk(mu_);
    Stats s;
    s.unique_objects = refs_.size();
    s.duplicate_objects = duplicate_objects_;
    s.saved_bytes = saved_bytes_;
    s.logical_bytes = logical_bytes_;
    return s;
}

void Dedup::reset() {
    std::lock_guard<std::mutex> lk(mu_);
    refs_.clear();
    duplicate_objects_ = 0;
    saved_bytes_ = 0;
    logical_bytes_ = 0;
}

} // namespace nr
