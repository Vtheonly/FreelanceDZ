"""FreelanceDZ v3 engine package.

Composition:
    native      — ctypes bridge to the C++20 SIMD core, pure-Python fallbacks
    analyzer    — deterministic business auditor (replaces the LLM stack)
    scorer      — explainable 0-100 priority scoring
    resolver    — entity resolution (blocking + native matching + DSU + merge)
    acquisition — streaming web acquisition (rate control, AIMD, pipeline)
"""

__all__: list[str] = []
