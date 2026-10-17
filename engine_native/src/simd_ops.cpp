#include "simd_ops.hpp"

#include <algorithm>
#include <cstring>
#include <vector>

#if defined(_MSC_VER)
#  include <intrin.h>
#else
#  include <cpuid.h>
#  if defined(__AVX2__)
#    include <immintrin.h>
#  endif
#endif

namespace fdz::simd {

Isa detect_isa() noexcept {
#if defined(__AVX512F__)
    return Isa::Avx512;
#elif defined(__AVX2__)
    return Isa::Avx2;
#elif defined(__SSE4_2__)
    return Isa::Sse42;
#else
    /* Generic build: runtime cpuid probe (no vector kernels compiled). */
#  if defined(_MSC_VER)
    int info[4];
    __cpuid(info, 1);
    const bool osxsave = (info[2] & (1 << 27)) != 0;
    const bool avx     = (info[2] & (1 << 28)) != 0;
    if (osxsave && avx) {
        __cpuidex(info, 7, 0);
        if (info[1] & (1 << 16)) return Isa::Avx512;
        if (info[1] & (1 << 5))  return Isa::Avx2;
    }
    if (info[2] & (1 << 19)) return Isa::Sse42;
#  else
    unsigned a = 0, b = 0, c = 0, d = 0;
    if (__get_cpuid(1, &a, &b, &c, &d)) {
        if (c & bit_OSXSAVE) {
            unsigned a7 = 0, b7 = 0, c7 = 0, d7 = 0;
            __cpuid_count(7, 0, a7, b7, c7, d7);
            if (b7 & bit_AVX512F) return Isa::Avx512;
            if (b7 & bit_AVX2)    return Isa::Avx2;
        }
        if (c & bit_SSE4_2) return Isa::Sse42;
    }
#  endif
    return Isa::Scalar;
#endif
}

// ---------------------------------------------------------------------------
// Myers bit-parallel Levenshtein (exact). Single word covers pattern lengths
// up to 64 — which spans essentially every business name in this domain.
// Longer strings fall back to a two-row DP (still exact, cache-friendly).
// ---------------------------------------------------------------------------

namespace {

inline uint32_t myers_word(std::string_view a, std::string_view b) noexcept {
    const size_t m = a.size();
    uint64_t peq[256];
    std::memset(peq, 0, sizeof(peq));
    for (size_t i = 0; i < m; ++i) {
        peq[static_cast<uint8_t>(a[i])] |= (1ULL << i);
    }
    const uint64_t top = (m >= 64) ? ~0ULL : ((1ULL << m) - 1ULL);
    uint64_t pv = ~0ULL;
    uint64_t mv = 0;
    uint32_t score = static_cast<uint32_t>(m);

    for (size_t j = 0; j < b.size(); ++j) {
        const uint64_t eq = peq[static_cast<uint8_t>(b[j])] & top;
        const uint64_t xv = eq | mv;
        const uint64_t xh = (((eq & pv) + pv) ^ pv) | eq;
        const uint64_t ph = mv | ~(xh | pv);
        const uint64_t mh = pv & xh;
        if (ph & (1ULL << (m - 1))) score++;
        if (mh & (1ULL << (m - 1))) score--;
        const uint64_t ph_shift = (ph << 1) | 1ULL;
        const uint64_t mh_shift = (mh << 1);
        pv = mh_shift | (~(xv | ph_shift) & top);
        mv = ph_shift & xv;
    }
    return score;
}

inline uint32_t dp_levenshtein(std::string_view a, std::string_view b) noexcept {
    const size_t m = a.size(), n = b.size();
    std::vector<uint32_t> prev(m + 1), cur(m + 1);
    for (size_t i = 0; i <= m; ++i) prev[i] = static_cast<uint32_t>(i);
    for (size_t j = 1; j <= n; ++j) {
        cur[0] = static_cast<uint32_t>(j);
        for (size_t i = 1; i <= m; ++i) {
            const uint32_t cost = (a[i - 1] == b[j - 1]) ? 0u : 1u;
            cur[i] = std::min({prev[i] + 1u, cur[i - 1] + 1u, prev[i - 1] + cost});
        }
        std::swap(prev, cur);
    }
    return prev[m];
}

} // namespace

uint32_t levenshtein_myers(std::string_view a, std::string_view b) noexcept {
    if (a.empty()) return static_cast<uint32_t>(b.size());
    if (b.empty()) return static_cast<uint32_t>(a.size());
    if (a.size() <= 64 && b.size() <= 64) return myers_word(a, b);
    return dp_levenshtein(a, b);
}

// ---------------------------------------------------------------------------
// Trigram bitsets + vectorized Jaccard
// ---------------------------------------------------------------------------

void trigram_bitset(std::string_view text, uint64_t out[4]) noexcept {
    out[0] = out[1] = out[2] = out[3] = 0;
    const size_t n = text.size();
    if (n < 3) return;
    for (size_t i = 0; i + 2 < n; ++i) {
        const uint32_t h = (static_cast<uint32_t>(static_cast<uint8_t>(text[i])) * 961u) ^
                           (static_cast<uint32_t>(static_cast<uint8_t>(text[i + 1])) * 31u) ^
                            static_cast<uint32_t>(static_cast<uint8_t>(text[i + 2]));
        const uint32_t bucket = h & 255u;
        out[bucket >> 6] |= (1ULL << (bucket & 63));
    }
}

namespace {

inline uint32_t popcount64(uint64_t v) noexcept {
#if defined(__GNUC__) || defined(__clang__)
    return static_cast<uint32_t>(__builtin_popcountll(v));
#elif defined(_MSC_VER)
    return static_cast<uint32_t>(__popcnt64(v));
#else
    uint32_t c = 0;
    while (v) { v &= v - 1; ++c; }
    return c;
#endif
}

} // namespace

/* 256-bit bitset -> a single AVX2 AND/OR + popcount lanes. On AVX-512-only
   hosts the AVX2 path is still available (AVX512F implies AVX2), so no
   512-bit variant is needed for a 32-byte bitset. */
float trigram_jaccard(const uint64_t a[4], const uint64_t b[4]) noexcept {
#if defined(__AVX2__)
    const __m256i va = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(a));
    const __m256i vb = _mm256_loadu_si256(reinterpret_cast<const __m256i*>(b));
    const __m256i vand = _mm256_and_si256(va, vb);
    const __m256i vor  = _mm256_or_si256(va, vb);
    alignas(32) uint64_t and_lane[4];
    alignas(32) uint64_t or_lane[4];
    _mm256_store_si256(reinterpret_cast<__m256i*>(and_lane), vand);
    _mm256_store_si256(reinterpret_cast<__m256i*>(or_lane), vor);
    const uint32_t inter = popcount64(and_lane[0]) + popcount64(and_lane[1]) +
                           popcount64(and_lane[2]) + popcount64(and_lane[3]);
    const uint32_t uni = popcount64(or_lane[0]) + popcount64(or_lane[1]) +
                         popcount64(or_lane[2]) + popcount64(or_lane[3]);
#else
    uint32_t inter = 0, uni = 0;
    for (int i = 0; i < 4; ++i) {
        inter += popcount64(a[i] & b[i]);
        uni   += popcount64(a[i] | b[i]);
    }
#endif
    if (uni == 0) return 0.0f;
    return static_cast<float>(inter) / static_cast<float>(uni);
}

} // namespace fdz::simd
