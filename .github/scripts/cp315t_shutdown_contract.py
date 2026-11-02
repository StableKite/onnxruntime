"""Verify original producer test binaries and wait for real Windows process completion."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict, cast

# This documented CPython runtime inspection API has an underscored name.
is_gil_enabled = cast(Callable[[], bool], vars(sys)["_is_gil_enabled"])


class Artifact(TypedDict):
    filename: str
    url: str
    bytes: int
    sha256: str


class Manifest(TypedDict):
    source_commit: str
    artifacts: list[Artifact]


def main() -> None:
    assert sys.platform == "win32" and sys.flags.gil is None and not is_gil_enabled()
    manifest = cast(
        Manifest,
        json.loads((Path(__file__).parent.parent / "testdata/cp315t_shutdown_artifacts.json").read_text("utf8")),
    )
    output = Path("onnx-shutdown-ci-evidence")
    output.mkdir(exist_ok=False)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="ort-shutdown-") as temporary:
        directory = Path(temporary)
        for artifact in manifest["artifacts"]:
            assert Path(artifact["filename"]).name == artifact["filename"]
            assert artifact["url"].startswith("https://github.com/StableKite/onnxruntime/releases/download/")
            with urllib.request.urlopen(artifact["url"], timeout=60) as response:
                content = response.read(4_000_000)
            assert len(content) == artifact["bytes"]
            assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
            (directory / artifact["filename"]).write_bytes(content)
        executable = directory / "onnxruntime_telemetry_shutdown_test.exe"
        library = directory / "onnxruntime_telemetry_shutdown_test_library.dll"
        for mode in ("unload", "process-exit", "global-lock", "sdk-lock", "sdk-activity"):
            argv = [str(executable), str(library), mode]
            start = time.monotonic()
            try:
                result = subprocess.run(argv, capture_output=True, timeout=15, check=False)
            except subprocess.TimeoutExpired as error:
                for stream, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                    content = value.encode() if isinstance(value, str) else value or b""
                    (output / (mode + "." + stream + ".log")).write_bytes(content)
                results.append({"argv": argv, "normal_process_completion": False, "timeout_seconds": 15})
                (output / "RESULT.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf8")
                raise
            (output / (mode + ".stdout.log")).write_bytes(result.stdout)
            (output / (mode + ".stderr.log")).write_bytes(result.stderr)
            results.append(
                {
                    "argv": argv,
                    "exit_code": result.returncode,
                    "normal_process_completion": True,
                    "elapsed_seconds": time.monotonic() - start,
                }
            )
            (output / "RESULT.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf8")
            assert result.returncode == 0, (mode, result.stdout, result.stderr)
    assert sys.flags.gil is None and not is_gil_enabled()
    receipt = {
        "source_commit": manifest["source_commit"],
        "producer_artifacts": manifest["artifacts"],
        "results": results,
    }
    (output / "RESULT.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
