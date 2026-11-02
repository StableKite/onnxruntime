// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

#include <Windows.h>

#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <mutex>
#include <thread>

#include "core/platform/telemetry_1ds.h"
#include <ILogManager.hpp>

namespace onnxruntime {

// Model SDK activity whose worker is stopped by normal Windows process exit.
// No thread is terminated by the test and no process-exit override is used.
struct OneDsTelemetryShutdownTestAccess {
  static bool HasLiveSdk() {
    return OneDsTelemetry::log_manager_ != nullptr && OneDsTelemetry::logger_.load() != nullptr;
  }

  static bool IsClean() {
    return OneDsTelemetry::global_register_count_.load() == 0 &&
           OneDsTelemetry::log_manager_ == nullptr && OneDsTelemetry::logger_.load() == nullptr &&
           OneDsTelemetry::config_.get() == nullptr;
  }

  static bool HoldLockUntilProcessExit(int kind) {
    struct Ready {
      std::mutex mutex;
      std::condition_variable changed;
      bool ready = false;
    };
    // The worker and its synchronization objects live until process reclamation.
    auto* ready = new Ready;
    std::unique_lock<std::mutex> lock(ready->mutex);
    std::thread([ready, kind] {
      auto hold = [ready] {
        {
          std::lock_guard<std::mutex> signal(ready->mutex);
          ready->ready = true;
        }
        ready->changed.notify_one();
        ::Sleep(INFINITE);
      };
      if (kind == 1) {
        std::lock_guard<std::mutex> telemetry_lock(OneDsTelemetry::global_mutex_);
        hold();
      } else if (kind == 2) {
        std::unique_lock<std::shared_mutex> telemetry_lock(OneDsTelemetry::mutex_);
        hold();
      } else {
        auto* manager = OneDsTelemetry::log_manager_;
        if (manager->StartActivity()) {
          hold();
          manager->EndActivity();
        }
      }
    }).detach();
    const bool acquired = ready->changed.wait_for(lock, std::chrono::seconds(5), [ready] { return ready->ready; });
    if (acquired) {
      std::fprintf(stderr, "Worker holds telemetry resource %d.\n", kind);
      std::fflush(stderr);
    }
    return acquired;
  }
};

}  // namespace onnxruntime

namespace {
struct Fixture {
  std::unique_ptr<onnxruntime::OneDsTelemetry> telemetry;
  ~Fixture() {
    if (telemetry) {
      std::fprintf(stderr, "Destroying real telemetry; process_shutdown=%d.\n", onnxruntime::IsProcessShuttingDown());
      std::fflush(stderr);
    }
  }
};

Fixture& GetFixture() {
  static Fixture fixture;
  return fixture;
}
}  // namespace

extern "C" __declspec(dllexport) int InitializeTelemetryShutdownTest(int kind) {
  auto& fixture = GetFixture();
  fixture.telemetry = std::make_unique<onnxruntime::OneDsTelemetry>();
  if (kind < 0 || kind > 3 || onnxruntime::IsProcessShuttingDown() ||
      !onnxruntime::OneDsTelemetryShutdownTestAccess::HasLiveSdk()) {
    return 1;
  }
  if (kind != 0 && !onnxruntime::OneDsTelemetryShutdownTestAccess::HoldLockUntilProcessExit(kind)) {
    return 2;
  }
  return 0;
}

extern "C" __declspec(dllexport) int ReleaseTelemetryShutdownTest() {
  if (onnxruntime::IsProcessShuttingDown()) {
    return 1;
  }
  GetFixture().telemetry.reset();
  return onnxruntime::OneDsTelemetryShutdownTestAccess::IsClean() ? 0 : 2;
}
