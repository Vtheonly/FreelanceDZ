// ============================================================================
// FreelanceDZ v3 — Native Engine Types (C ABI shared with Python ctypes)
//
// Design notes (from Engine Architecture principles):
//  - Hot state is bit-packed channel flags (u64) so scoring branches on bits.
//  - Batch scoring operates on parallel arrays (SoA) for vectorization.
//  - All structs are extern "C", fixed-layout, no STL across the boundary.
//  - Strings are bounded fixed buffers (zero-copy into preallocated arenas).
// ============================================================================
#ifndef FDZ_ENGINE_TYPES_H
#define FDZ_ENGINE_TYPES_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Channel-presence bit flags (hot state for scoring/audit). */
#define FDZ_FLAG_WEBSITE   (1ULL << 0)
#define FDZ_FLAG_SSL       (1ULL << 1)
#define FDZ_FLAG_PHONE     (1ULL << 2)
#define FDZ_FLAG_MOBILE    (1ULL << 3)
#define FDZ_FLAG_WHATSAPP  (1ULL << 4)
#define FDZ_FLAG_EMAIL     (1ULL << 5)
#define FDZ_FLAG_SOCIAL    (1ULL << 6)
#define FDZ_FLAG_ADDRESS   (1ULL << 7)
#define FDZ_FLAG_GEO       (1ULL << 8)

/* HTML extraction result. Keep in sync with engine/native.py mirror. */
#define FDZ_MAX_LINKS  128
#define FDZ_MAX_PHONES 16
#define FDZ_JSONLD_CAP 8192

typedef struct {
    char url[256];
} FdzLink;

typedef struct {
    char raw[32];
} FdzPhone;

typedef struct {
    char title[192];
    char meta_description[256];
    char canonical_url[256];
    char og_title[192];
    char og_description[256];
    char email[96];
    char lang[16];
    char json_ld[FDZ_JSONLD_CAP];
    uint32_t json_ld_len;
    uint32_t link_count;
    uint32_t phone_count;
    FdzLink links[FDZ_MAX_LINKS];
    FdzPhone phones[FDZ_MAX_PHONES];
} FdzExtraction;

/* ISA levels reported by engine_isa_level(). */
#define FDZ_ISA_SCALAR 0
#define FDZ_ISA_SSE42  1
#define FDZ_ISA_AVX2   2
#define FDZ_ISA_AVX512 3

#ifdef __cplusplus
}
#endif

#endif /* FDZ_ENGINE_TYPES_H */
