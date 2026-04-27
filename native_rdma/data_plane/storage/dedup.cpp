#include "dedup.h"
#include <openssl/sha.h>
#include <cstring>

namespace nr {

uint64_t Dedup::observe(const std::string& data, bool* duplicate) {
    uint8_t md[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const uint8_t*>(data.data()), data.size(), md);
    uint64_t fp = 0;
    std::memcpy(&fp, md, sizeof(fp));
    std::lock_guard<std::mutex> lk(mu_);
    auto it = refs_.find(fp);
    if (it == refs_.end()) {
        refs_[fp] = 1;
        if (duplicate) *duplicate = false;
    } else {
        it->second++;
        if (duplicate) *duplicate = true;
    }
    return fp;
}

void Dedup::release(uint64_t fp) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = refs_.find(fp);
    if (it == refs_.end()) return;
    if (--it->second == 0) refs_.erase(it);
}

} // namespace nr
