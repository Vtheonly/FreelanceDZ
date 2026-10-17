#!/usr/bin/env bash
# ============================================================================
# Build the FreelanceDZ native engine core.
#
# Strategy: probe the host CPU at build time and enable the widest safe ISA.
# The library itself ALSO probes at runtime (engine_isa_level) and every
# kernel has a scalar path compiled in, so a binary built for AVX2 still runs
# (in scalar mode for vector kernels) on older hosts.
#
# Usage:  bash engine_native/build.sh [output-dir]
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-$ROOT}"
SRC_DIR="$ROOT/src"
INC_DIR="$ROOT/include"

CXX="${CXX:-g++}"
CXXFLAGS_BASE="-std=c++20 -O2 -fPIC -Wall -Wextra -fno-plt"

# --- Probe host ISA --------------------------------------------------------
ISA_FLAGS=""
ARCH_TAG="generic"
if [ -r /proc/cpuinfo ]; then
    if grep -qm1 'avx512f' /proc/cpuinfo; then
        ISA_FLAGS="-mavx2 -mfma -mavx512f -mpopcnt"
        ARCH_TAG="avx512"
    elif grep -qm1 'avx2' /proc/cpuinfo; then
        ISA_FLAGS="-mavx2 -mfma -mpopcnt"
        ARCH_TAG="avx2"
    elif grep -qm1 'sse4_2' /proc/cpuinfo; then
        ISA_FLAGS="-msse4.2 -mpopcnt"
        ARCH_TAG="sse42"
    fi
fi

LIB_NAME="libfdz_engine.so"
OUT_PATH="$OUT_DIR/$LIB_NAME"

echo "[fdz-native] compiler : $($CXX --version | head -1)"
echo "[fdz-native] isa      : $ARCH_TAG ($ISA_FLAGS)"
echo "[fdz-native] output   : $OUT_PATH"

$CXX $CXXFLAGS_BASE $ISA_FLAGS \
    -I"$INC_DIR" \
    -shared \
    "$SRC_DIR/simd_ops.cpp" "$SRC_DIR/engine_c_api.cpp" \
    -o "$OUT_PATH"

echo "[fdz-native] built successfully."
