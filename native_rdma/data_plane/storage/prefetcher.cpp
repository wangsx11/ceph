#include "prefetcher.h"

namespace nr {

void Prefetcher::on_access(std::string_view) {
    // TODO: sliding-window stride detection + 1-gram Markov.
}

bool Prefetcher::should_prefetch(std::string_view) const {
    return false;
}

} // namespace nr
