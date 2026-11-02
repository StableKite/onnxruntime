// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

#include <Windows.h>

#include <cstdio>
#include <cwchar>

int wmain(int argc, wchar_t** argv) {
  if (argc != 3) {
    return 1;
  }
  const bool unload = std::wcscmp(argv[2], L"unload") == 0;
  const int kind = std::wcscmp(argv[2], L"global-lock") == 0 ? 1 : std::wcscmp(argv[2], L"sdk-lock") == 0   ? 2
                                                               : std::wcscmp(argv[2], L"sdk-activity") == 0 ? 3
                                                                                                            : 0;
  HMODULE library = ::LoadLibraryW(argv[1]);
  if (library == nullptr) {
    std::fprintf(stderr, "LoadLibrary failed: %lu\n", ::GetLastError());
    return 2;
  }
  using Initialize = int (*)(int);
  auto initialize = reinterpret_cast<Initialize>(::GetProcAddress(library, "InitializeTelemetryShutdownTest"));
  if (initialize == nullptr || initialize(kind) != 0) {
    return 3;
  }
  if (unload) {
    using Release = int (*)();
    auto release = reinterpret_cast<Release>(::GetProcAddress(library, "ReleaseTelemetryShutdownTest"));
    if (release == nullptr || release() != 0 || !::FreeLibrary(library)) {
      return 4;
    }
    if (::GetModuleHandleW(argv[1]) != nullptr) {
      return 5;
    }
    std::puts("SDK cleanup and dynamic DLL unload completed.");
  }
  std::puts("Real telemetry initialized; returning normally from main.");
  std::fflush(stdout);
  return 0;
}
