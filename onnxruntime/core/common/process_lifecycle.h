// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

#pragma once

#include <atomic>

// Set by DllMain only for process termination, never for dynamic DLL unload.
extern std::atomic<bool> g_is_shutting_down;

namespace onnxruntime {

inline bool IsProcessShuttingDown() noexcept {
  return g_is_shutting_down.load(std::memory_order_relaxed);
}

}  // namespace onnxruntime
