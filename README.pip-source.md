# CPython 3.15t CPU dependency delivery

Install the default branch with ordinary pip. Qualified platforms listed in
`binary_wheels.json` receive their original CPU wheel. Its SHA256 and unchanged
native source are checked before delivery. Build configuration and native-source
edits select the upstream source build instead. Windows x86-64 is qualified;
Linux source and test work is still in progress and is not represented as PASS.

The source fallback uses `tools/ci_build/build.py` with the complete standard
CPU operator set. It requires the platform's normal C++ development tools;
build dependencies are provided through PEP 517 isolation. The backend does
not alter the consumer environment or override the runtime GIL setting.

These are engineering dependency artifacts. They do not represent a completed
StableKite product release. Producer tests, wheel checksums and platform limits
are recorded on the linked engineering artifact release.

The Windows wheel `1.31.1+stablekite.1` includes a native 1DS process-termination
fix. It retains normal telemetry operation, SDK cleanup, and dynamic DLL unload.
The delivery CI also verifies the original producer shutdown-test binaries and
waits for actual child-process completion, including an active SDK worker at exit.
