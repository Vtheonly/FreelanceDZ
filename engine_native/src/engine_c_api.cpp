// ============================================================================
// Scoring + name-matching session + Bloom + HTML extraction — C API surface.
// Every symbol is batch-oriented where hot, extern "C", ctypes-friendly.
// ============================================================================
#include "engine_types.h"
#include "simd_ops.hpp"
#include "bloom.hpp"

#include <algorithm>
#include <cstring>
#include <string>
#include <string_view>
#include <vector>

// ---------------------------------------------------------------------------
// ISA report
// ---------------------------------------------------------------------------
extern "C" uint32_t engine_isa_level(void) {
    return static_cast<uint32_t>(fdz::simd::detect_isa());
}

// ---------------------------------------------------------------------------
// Deterministic SoA batch scoring.
// Weights mirror engine/scorer.py fallback exactly (parity is unit-tested).
//   digital health: 10 base +35 website +10 ssl +15 phone +10 email
//                   +10 social (+5 per extra social up to +10) +5 address
//   priority: reachability(<=35) + substance(<=25) + deficit(<=25) + freshness(<=15)
// Freshness arrives as u8 bucket index 0..4 -> {15,10,7,4,2}.
// ---------------------------------------------------------------------------
extern "C" void engine_score_batch(
    const uint64_t* flags, const uint8_t* social_counts, const uint8_t* freshness_buckets,
    uint32_t count, float* out_priority, uint8_t* out_digital
) {
    if (!flags || !out_priority || !out_digital) return;

    for (uint32_t i = 0; i < count; ++i) {
        const uint64_t f = flags[i];

        uint32_t health = 10;
        if (f & FDZ_FLAG_WEBSITE) { health += 35; if (f & FDZ_FLAG_SSL) health += 10; }
        if (f & FDZ_FLAG_PHONE)   health += 15;
        if (f & FDZ_FLAG_EMAIL)   health += 10;
        if (f & FDZ_FLAG_SOCIAL)  health += 10 + std::min<uint32_t>(social_counts[i], 2u) * 5u;
        if (f & FDZ_FLAG_ADDRESS) health += 5;
        if (health > 100) health = 100;
        out_digital[i] = static_cast<uint8_t>(health);

        float reach = 0.0f;
        if (f & FDZ_FLAG_PHONE)    reach += 15.0f;
        if (f & FDZ_FLAG_MOBILE)   reach += 10.0f;
        if (f & FDZ_FLAG_WHATSAPP) reach += 5.0f;
        if (f & FDZ_FLAG_EMAIL)    reach += 5.0f;

        float substance = 0.0f;
        if (f & FDZ_FLAG_WEBSITE) substance += 10.0f;
        if (f & FDZ_FLAG_SOCIAL)  substance += 5.0f;
        if (f & FDZ_FLAG_ADDRESS) substance += 5.0f;
        if (f & FDZ_FLAG_GEO)     substance += 5.0f;

        const float deficit = (100.0f - static_cast<float>(health)) * 0.25f;

        static constexpr float FRESH_PTS[5] = {15.0f, 10.0f, 7.0f, 4.0f, 2.0f};
        const uint8_t fb = (freshness_buckets ? freshness_buckets[i] : 4u);
        const float fresh = FRESH_PTS[fb < 5 ? fb : 4u];

        float total = reach + substance + deficit + fresh;
        if (total > 100.0f) total = 100.0f;
        out_priority[i] = total;
    }
}

// ---------------------------------------------------------------------------
// Name-matching session (entity resolution hot path).
//   engine_names_reset(capacity)     -> begin session
//   engine_names_add(name, len)      -> index (or -1 on overflow)
//   engine_names_match_pairs(...)    -> batch similarity with prefilter
// Pairs whose bitset-Jaccard < jaccard_prefilter score 0 without Myers.
// Scores below name_threshold are returned as 0.0.
// ---------------------------------------------------------------------------
namespace {
struct NameEntry {
    std::string text;
    uint64_t bits[4];
};
std::vector<NameEntry> g_names;
size_t g_names_capacity = 0;
fdz::BlockedBloom g_bloom(2'000'000, 0.01);
bool g_bloom_init_done = false;
} // namespace

extern "C" int32_t engine_names_reset(uint32_t expected_count) {
    g_names_capacity = expected_count ? expected_count : 4096;
    g_names.clear();
    g_names.reserve(g_names_capacity);
    return static_cast<int32_t>(g_names.size());
}

extern "C" int32_t engine_names_add(const char* name, uint32_t len) {
    if (!name || len == 0) return -1;
    if (g_names.size() >= g_names_capacity) return -1;
    std::string_view sv(name, len);
    NameEntry e;
    e.text.assign(sv);
    fdz::simd::trigram_bitset(sv, e.bits);
    g_names.push_back(std::move(e));
    return static_cast<int32_t>(g_names.size() - 1);
}

/* Batched registration: one FFI call for N names (pointers + lengths).
   Removes the per-string ctypes overhead that dominated small-call workloads. */
extern "C" int32_t engine_names_add_many(const char* const* names, const uint32_t* lens, uint32_t count) {
    if (!names || !lens || count == 0) return -1;
    int32_t first = -1;
    for (uint32_t i = 0; i < count; ++i) {
        const char* name = names[i];
        const uint32_t len = lens[i];
        if (!name || len == 0 || g_names.size() >= g_names_capacity) continue;
        std::string_view sv(name, len);
        NameEntry e;
        e.text.assign(sv);
        fdz::simd::trigram_bitset(sv, e.bits);
        if (first < 0) first = static_cast<int32_t>(g_names.size());
        g_names.push_back(std::move(e));
    }
    return first;  // index of the first name added this call (-1 if none)
}

extern "C" int32_t engine_names_match_pairs(
    const uint32_t* idx_a, const uint32_t* idx_b, uint32_t pair_count,
    float jaccard_prefilter, float name_threshold, float* out_scores
) {
    if (!idx_a || !idx_b || !out_scores || pair_count == 0) return 0;
    uint32_t written = 0;
    for (uint32_t p = 0; p < pair_count; ++p) {
        const uint32_t ia = idx_a[p], ib = idx_b[p];
        if (ia >= g_names.size() || ib >= g_names.size()) { out_scores[p] = 0.0f; continue; }
        const NameEntry& a = g_names[ia];
        const NameEntry& b = g_names[ib];

        const float jac = fdz::simd::trigram_jaccard(a.bits, b.bits);
        if (jac < jaccard_prefilter) { out_scores[p] = 0.0f; continue; }

        const uint32_t dist = fdz::simd::levenshtein_myers(a.text, b.text);
        const uint32_t max_len = std::max<uint32_t>(
            static_cast<uint32_t>(a.text.size()), static_cast<uint32_t>(b.text.size()));
        const float sim = max_len ? (1.0f - static_cast<float>(dist) / static_cast<float>(max_len)) : 0.0f;
        out_scores[p] = (sim >= name_threshold) ? sim : 0.0f;
        ++written;
    }
    return static_cast<int32_t>(written);
}

// ---------------------------------------------------------------------------
// Single-shot helpers (used for parity tests and small ad-hoc calls).
// ---------------------------------------------------------------------------
extern "C" uint32_t engine_levenshtein(const char* a, uint32_t la, const char* b, uint32_t lb) {
    if (!a || !b) return la + lb;
    return fdz::simd::levenshtein_myers(std::string_view(a, la), std::string_view(b, lb));
}

extern "C" float engine_trigram_jaccard(const char* a, uint32_t la, const char* b, uint32_t lb) {
    if (!a || !b || la == 0 || lb == 0) return 0.0f;
    uint64_t ba[4], bb[4];
    fdz::simd::trigram_bitset(std::string_view(a, la), ba);
    fdz::simd::trigram_bitset(std::string_view(b, lb), bb);
    return fdz::simd::trigram_jaccard(ba, bb);
}

// ---------------------------------------------------------------------------
// Bloom filter (URL dedup accelerator for the crawl frontier).
// ---------------------------------------------------------------------------
extern "C" uint32_t engine_bloom_init(uint64_t expected_items, double fpr) {
    if (!g_bloom_init_done || expected_items > 0) {
        if (expected_items == 0) expected_items = 2'000'000;
        if (fpr <= 0.0) fpr = 0.01;
        g_bloom = fdz::BlockedBloom(static_cast<size_t>(expected_items), fpr);
        g_bloom_init_done = true;
    }
    return 1;
}

extern "C" uint32_t engine_bloom_test_and_add(const char* url, uint32_t len) {
    if (!url || len == 0) return 0;
    return g_bloom.test_and_add(std::string_view(url, len)) ? 1u : 0u;
}

extern "C" uint32_t engine_bloom_test(const char* url, uint32_t len) {
    if (!url || len == 0) return 0;
    return g_bloom.test(std::string_view(url, len)) ? 1u : 0u;
}

extern "C" void engine_bloom_clear(void) { g_bloom.clear(); }

extern "C" uint64_t engine_bloom_size(void) { return g_bloom.size(); }

// ---------------------------------------------------------------------------
// Zero-copy HTML scanner. Extracts structural signals from raw bytes without
// building a DOM: <title>, meta description/canonical/og:*, lang, JSON-LD
// payload, anchor hrefs (split into links / tel: / mailto:), and Algerian
// phone patterns (05/06/07/+213/00213) from inter-tag text.
// Malformed pages that yield nothing here fall back to BeautifulSoup upstream.
// ---------------------------------------------------------------------------
namespace {

inline char lower_ascii(char c) noexcept {
    return (c >= 'A' && c <= 'Z') ? static_cast<char>(c + 32) : c;
}

inline size_t find_ci(std::string_view hay, std::string_view needle, size_t from) noexcept {
    if (needle.empty() || hay.size() < needle.size()) return std::string_view::npos;
    for (size_t i = from; i + needle.size() <= hay.size(); ++i) {
        size_t k = 0;
        while (k < needle.size() && lower_ascii(hay[i + k]) == lower_ascii(needle[k])) ++k;
        if (k == needle.size()) return i;
    }
    return std::string_view::npos;
}

inline bool ci_starts_with(std::string_view s, std::string_view prefix) noexcept {
    if (s.size() < prefix.size()) return false;
    for (size_t i = 0; i < prefix.size(); ++i) {
        if (lower_ascii(s[i]) != lower_ascii(prefix[i])) return false;
    }
    return true;
}

inline void copy_bounded(char* dst, size_t cap, std::string_view src) noexcept {
    const size_t n = std::min(src.size(), cap - 1);
    std::memcpy(dst, src.data(), n);
    dst[n] = '\0';
}

inline std::string_view strip_ws(std::string_view s) noexcept {
    while (!s.empty() && (s.front() == ' ' || s.front() == '\t' || s.front() == '\r' || s.front() == '\n')) s.remove_prefix(1);
    while (!s.empty() && (s.back() == ' ' || s.back() == '\t' || s.back() == '\r' || s.back() == '\n')) s.remove_suffix(1);
    return s;
}

/* Extract a quoted/unquoted attribute value from within a tag body. */
inline std::string_view attr_value(std::string_view tag, std::string_view attr) noexcept {
    const size_t pos = find_ci(tag, attr, 0);
    if (pos == std::string_view::npos) return {};
    size_t i = pos + attr.size();
    while (i < tag.size() && tag[i] == ' ') ++i;
    if (i >= tag.size() || tag[i] != '=') return {};
    ++i;
    while (i < tag.size() && tag[i] == ' ') ++i;
    if (i >= tag.size()) return {};
    if (tag[i] == '"' || tag[i] == '\'') {
        const char q = tag[i++];
        const size_t end = tag.find(q, i);
        if (end == std::string_view::npos) return {};
        return tag.substr(i, end - i);
    }
    const size_t end = tag.find_first_of(" >\t\r\n", i);
    return (end == std::string_view::npos) ? tag.substr(i) : tag.substr(i, end - i);
}

inline bool is_phone_cont(char c) noexcept {
    return (c >= '0' && c <= '9') || c == ' ' || c == '-' || c == '.' || c == '+';
}

/* Scan a text run for Algerian phone patterns; append to out. */
inline void scan_phones(std::string_view text, FdzExtraction* out) noexcept {
    static constexpr std::string_view PREFIXES[] = {"+213", "00213", "05", "06", "07"};
    for (std::string_view pref : PREFIXES) {
        size_t from = 0;
        while (out->phone_count < FDZ_MAX_PHONES) {
            const size_t hit = text.find(pref, from);
            if (hit == std::string_view::npos) break;
            from = hit + 1;
            /* Anchor: previous char must not be a digit (avoid inside-numbers). */
            if (hit > 0 && text[hit - 1] >= '0' && text[hit - 1] <= '9') continue;
            size_t end = hit;
            while (end < text.size() && is_phone_cont(text[end])) ++end;
            std::string_view num = text.substr(hit, end - hit);
            /* Trim trailing separators. */
            while (!num.empty() && (num.back() == ' ' || num.back() == '-' || num.back() == '.')) num.remove_suffix(1);
            /* Count digits to reject short fragments. */
            size_t digits = 0;
            for (char c : num) if (c >= '0' && c <= '9') ++digits;
            if (digits >= 9 && num.size() < 32) {
                copy_bounded(out->phones[out->phone_count].raw, sizeof(out->phones[0].raw), num);
                ++out->phone_count;
            }
        }
        if (out->phone_count >= FDZ_MAX_PHONES) return;
    }
}

} // namespace

extern "C" void engine_extract_html(const char* html, uint32_t len, FdzExtraction* out) {
    if (!html || len == 0 || !out) return;
    std::memset(out, 0, sizeof(*out));

    const std::string_view doc(html, len);
    bool in_jsonld = false;

    size_t pos = 0;
    while (pos < doc.size()) {
        const size_t lt = doc.find('<', pos);
        if (lt == std::string_view::npos) break;
        const size_t gt = doc.find('>', lt);
        if (gt == std::string_view::npos) break;
        const std::string_view tag = doc.substr(lt, gt - lt + 1);
        const std::string_view inner = doc.substr(gt + 1);

        /* <title> */
        if (out->title[0] == '\0' && ci_starts_with(tag.substr(std::min<size_t>(1, tag.size())), "title")) {
            const size_t end = find_ci(inner, "</title>", 0);
            if (end != std::string_view::npos) {
                copy_bounded(out->title, sizeof(out->title), strip_ws(inner.substr(0, end)));
            }
        }
        /* lang on <html ...> */
        else if (out->lang[0] == '\0' && ci_starts_with(tag.substr(std::min<size_t>(1, tag.size())), "html")) {
            const std::string_view l = attr_value(tag, "lang");
            if (!l.empty()) copy_bounded(out->lang, sizeof(out->lang), l);
        }
        /* <meta ...> family */
        else if (ci_starts_with(tag.substr(std::min<size_t>(1, tag.size())), "meta")) {
            const std::string_view name = attr_value(tag, "name");
            const std::string_view prop = attr_value(tag, "property");
            const std::string_view content = attr_value(tag, "content");
            if (!content.empty()) {
                if (ci_starts_with(name, "description") && out->meta_description[0] == '\0') {
                    copy_bounded(out->meta_description, sizeof(out->meta_description), content);
                } else if (ci_starts_with(prop, "og:title") && out->og_title[0] == '\0') {
                    copy_bounded(out->og_title, sizeof(out->og_title), content);
                } else if (ci_starts_with(prop, "og:description") && out->og_description[0] == '\0') {
                    copy_bounded(out->og_description, sizeof(out->og_description), content);
                }
            }
        }
        /* <link rel=canonical> */
        else if (out->canonical_url[0] == '\0' && ci_starts_with(tag.substr(std::min<size_t>(1, tag.size())), "link")) {
            const std::string_view rel = attr_value(tag, "rel");
            if (ci_starts_with(rel, "canonical")) {
                const std::string_view href = attr_value(tag, "href");
                if (!href.empty()) copy_bounded(out->canonical_url, sizeof(out->canonical_url), href);
            }
        }
        /* <a href=...> */
        else if (ci_starts_with(tag.substr(std::min<size_t>(1, tag.size())), "a ") ||
                 ci_starts_with(tag.substr(std::min<size_t>(1, tag.size())), "a>")) {
            const std::string_view href = attr_value(tag, "href");
            if (!href.empty()) {
                if (ci_starts_with(href, "tel:")) {
                    const std::string_view num = href.substr(4);
                    if (!num.empty() && out->phone_count < FDZ_MAX_PHONES) {
                        copy_bounded(out->phones[out->phone_count].raw, sizeof(out->phones[0].raw), num);
                        ++out->phone_count;
                    }
                } else if (ci_starts_with(href, "mailto:") && out->email[0] == '\0') {
                    std::string_view em = href.substr(7);
                    const size_t cut = em.find_first_of("?& ");
                    if (cut != std::string_view::npos) em = em.substr(0, cut);
                    if (!em.empty()) copy_bounded(out->email, sizeof(out->email), em);
                } else if (href[0] != '#' && !ci_starts_with(href, "javascript:") &&
                           out->link_count < FDZ_MAX_LINKS && href.size() < 256) {
                    copy_bounded(out->links[out->link_count].url, sizeof(out->links[0].url), href);
                    ++out->link_count;
                }
            }
        }
        /* <script type="application/ld+json"> payload */
        else if (ci_starts_with(tag.substr(std::min<size_t>(1, tag.size())), "script")) {
            const std::string_view type = attr_value(tag, "type");
            if (ci_starts_with(type, "application/ld+json") && !in_jsonld && out->json_ld_len == 0) {
                const size_t end = find_ci(inner, "</script>", 0);
                std::string_view payload = (end != std::string_view::npos) ? inner.substr(0, end) : inner.substr(0, FDZ_JSONLD_CAP);
                if (payload.size() > FDZ_JSONLD_CAP - 1) payload = payload.substr(0, FDZ_JSONLD_CAP - 1);
                copy_bounded(out->json_ld, sizeof(out->json_ld), payload);
                out->json_ld_len = static_cast<uint32_t>(std::min(payload.size(), sizeof(out->json_ld) - 1));
                in_jsonld = true;
                pos = gt + 1 + (end != std::string_view::npos ? end + 9 : payload.size());
                continue;
            }
        }

        /* Phone scan over the text run following this tag. */
        if (out->phone_count < FDZ_MAX_PHONES) {
            const size_t next_lt = inner.find('<');
            const std::string_view text_run = (next_lt != std::string_view::npos)
                ? inner.substr(0, next_lt) : inner.substr(0, std::min<size_t>(inner.size(), 4096));
            if (text_run.size() >= 9) scan_phones(text_run, out);
        }

        pos = gt + 1;
    }
}
