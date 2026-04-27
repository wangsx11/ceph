#include "compress.h"

#if defined(NR_USE_ZSTD)
#include <zstd.h>
#endif
#if defined(NR_USE_LZ4)
#include <lz4.h>
#endif

namespace nr {

CompressAlgo CompressEngine::pick(size_t size) {
    if (size < 4096) return CompressAlgo::NONE;
#if defined(NR_USE_ZSTD)
    return CompressAlgo::ZSTD;
#elif defined(NR_USE_LZ4)
    return CompressAlgo::LZ4;
#else
    return CompressAlgo::NONE;
#endif
}

bool CompressEngine::compress(CompressAlgo a, const std::string& in, std::string* out) {
    if (a == CompressAlgo::NONE || !out) { if (out) *out = in; return true; }
#if defined(NR_USE_ZSTD)
    if (a == CompressAlgo::ZSTD) {
        size_t bound = ZSTD_compressBound(in.size());
        out->resize(bound);
        size_t n = ZSTD_compress(&(*out)[0], bound, in.data(), in.size(), 3);
        if (ZSTD_isError(n)) return false;
        out->resize(n);
        return true;
    }
#endif
#if defined(NR_USE_LZ4)
    if (a == CompressAlgo::LZ4) {
        int bound = LZ4_compressBound((int)in.size());
        out->resize(bound);
        int n = LZ4_compress_default(in.data(), &(*out)[0],
                                     (int)in.size(), bound);
        if (n <= 0) return false;
        out->resize(n);
        return true;
    }
#endif
    *out = in;
    return true;
}

bool CompressEngine::decompress(CompressAlgo a, const std::string& in, std::string* out) {
    if (a == CompressAlgo::NONE || !out) { if (out) *out = in; return true; }
#if defined(NR_USE_ZSTD)
    if (a == CompressAlgo::ZSTD) {
        unsigned long long sz = ZSTD_getFrameContentSize(in.data(), in.size());
        if (sz == ZSTD_CONTENTSIZE_ERROR || sz == ZSTD_CONTENTSIZE_UNKNOWN)
            return false;
        out->resize((size_t)sz);
        size_t n = ZSTD_decompress(&(*out)[0], (size_t)sz,
                                   in.data(), in.size());
        if (ZSTD_isError(n)) return false;
        out->resize(n);
        return true;
    }
#endif
#if defined(NR_USE_LZ4)
    if (a == CompressAlgo::LZ4) {
        // LZ4 has no frame header: try expanding the output until it fits,
        // capped at 16x the compressed size (demo-safe; real code would
        // prepend the original size in a 4-byte header).
        for (int mult = 4; mult <= 16; mult *= 2) {
            size_t cap = in.size() * (size_t)mult + 64;
            out->resize(cap);
            int n = LZ4_decompress_safe(in.data(), &(*out)[0],
                                        (int)in.size(), (int)cap);
            if (n >= 0) { out->resize((size_t)n); return true; }
        }
        return false;
    }
#endif
    *out = in;
    return true;
}

} // namespace nr
