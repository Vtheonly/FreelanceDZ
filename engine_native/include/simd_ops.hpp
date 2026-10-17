// ============================================================================
// SIMD primitives: ISA detection, Myers bit-parallel Levenshtein,
// trigram bitsets + vectorized Jaccard similarity.
// Runtime dispatch: compiled once, vector kernels guarded by __AVX2__ etc.;
// ISA level reported so callers can verify dispatch targets.
// ============================================================================
#ifndef FDZ_SIMD_OPS_HPP
#define FDZ_SIMD_OPS_HPP

#include <cstdint>
#include <cstddef>
#include <string_view>

namespace fdz::simd {

enum class Isa : int { Scalar = 0, Sse42 = 1, Avx2 = 2, Avx512 = 3 };

Isa detect_isa() noexcept;

/* Myers 1999 bit-parallel Levenshtein. O(ceil(n/64) * m) words; exact.
   Handles arbitrary lengths via multi-word fallback. */
uint32_t levenshtein_myers(std::string_view a, std::string_view b) noexcept;

/* 256-bit trigram presence bitset (4 x u64). Hash trigrams into 256 buckets. */
void trigram_bitset(std::string_view text, uint64_t out[4]) noexcept;

/* Jaccard similarity over two 256-bit trigram bitsets. */
float trigram_jaccard(const uint64_t a[4], const uint64_t b[4]) noexcept;

} // namespace fdz::simd

#endif
