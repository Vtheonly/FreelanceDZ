# ADR-002 · Retire the C++ "SIMD" core for optimized pure Python

**Status**: accepted (v4 Task 13)
**Context**: `engine_native/` shipped a C++20 core loaded via ctypes. Its
HTML scanner contained no actual SIMD, its global bloom filter had
thread-safety bugs and leaked state across instances, and its
Levenshtein was slower than rapidfuzz for our short business names. The
compiled `.so` also complicated every deployment (builder stage, cross-
platform builds) and was never present in practice.
**Decision**: delete `engine_native/` and the ctypes bridge; implement
`engine/fastops.py` with pre-compiled regex HTML scanning, rapidfuzz
Levenshtein, a per-instance bounded URL dedup, and the SoA scoring pass.
**Consequences**: no compiler in the Docker build; measured 9.2× faster
HTML extraction than the BS4 path production actually ran; semantics
locked by `test_fastops.py` (migrated from the old parity suite). The
pure-Python scoring pass is ~13% slower than the old fallback loop — the
documented cost of the new opportunity arithmetic, at ~1M leads/s.
