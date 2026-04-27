#pragma once
#include <string>
#include <cstdint>

namespace nr {

enum class CompressAlgo : uint8_t { NONE = 0, ZSTD = 1, LZ4 = 2 };

class CompressEngine {
public:
    static bool compress  (CompressAlgo a, const std::string& in, std::string* out);
    static bool decompress(CompressAlgo a, const std::string& in, std::string* out);
    // Picks an algo or NONE depending on size/entropy.
    static CompressAlgo pick(size_t size);
};

} // namespace nr
