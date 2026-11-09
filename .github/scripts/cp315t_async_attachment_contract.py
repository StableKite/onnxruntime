"""Check native main-interpreter callbacks around ordinary child shutdown."""

from __future__ import annotations

import importlib
import json
import os
import queue
import subprocess
import sys
import threading
from concurrent import interpreters
from pathlib import Path


def exercise(mode: str, model: Path) -> None:
    assert sys.flags.gil is None and not sys._is_gil_enabled()
    child = None
    if mode == "closed-before-import":
        child = interpreters.create()
        child.exec("pass")
        child.close()
        child = None

    np = importlib.import_module("numpy")
    ort = importlib.import_module("onnxruntime")

    main_id = interpreters.get_current().id
    main_thread = threading.get_native_id()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 2
    sessions = [ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"]) for _ in range(2)]
    inputs = np.array([[1, 2], [3, 4]], dtype=np.float32)
    expected = inputs @ np.array([[2, 3], [5, 7]], dtype=np.float32) + np.array([11, 13], dtype=np.float32)
    entered = [threading.Event(), threading.Event()]
    completed = [threading.Event(), threading.Event()]
    release = threading.Event()
    results = queue.SimpleQueue()

    def callback(outputs, index, error):
        try:
            results.put(
                (index, outputs, error, threading.get_native_id(), interpreters.get_current().id, sys._is_gil_enabled())
            )
            entered[index].set()
            assert release.wait(20)
        finally:
            completed[index].set()

    if mode in {"closed-after-import", "close-during-callback"}:
        child = interpreters.create()
        child.exec("pass")
        if mode == "closed-after-import":
            child.close()
            child = None
    for index, session in enumerate(sessions):
        np.testing.assert_array_equal(session.run(["y"], {"x": inputs})[0], expected)
        session.run_async(["y"], {"x": inputs}, callback, index)
    try:
        assert all(event.wait(20) for event in entered)
        if child is not None:
            child.close()
            child = None
    finally:
        release.set()
    assert all(event.wait(20) for event in completed)
    threads = []
    indices = set()
    for _ in sessions:
        index, outputs, error, thread_id, interpreter_id, gil = results.get_nowait()
        assert not error and interpreter_id == main_id and not gil and thread_id != main_thread
        np.testing.assert_array_equal(outputs[0], expected)
        indices.add(index)
        threads.append(thread_id)
    assert indices == {0, 1}
    assert sys.flags.gil is None and not sys._is_gil_enabled()
    print(
        json.dumps(
            {
                "status": "PASS",
                "mode": mode,
                "version": ort.__version__,
                "GIL": False,
                "main_interpreter": main_id,
                "native_callback_threads": threads,
            }
        ),
        flush=True,
    )


def main() -> None:
    if sys.argv[1] == "--child":
        exercise(sys.argv[2], Path(sys.argv[3]))
        return
    model = Path(sys.argv[1]).resolve(strict=True)
    output = Path("ort-async-attachment-evidence")
    output.mkdir(exist_ok=False)
    env = {name: value for name, value in os.environ.items() if name not in {"PYTHON_GIL", "PYTHONHOME", "PYTHONPATH"}}
    cases = []
    for mode in ("none", "closed-before-import", "closed-after-import", "close-during-callback"):
        argv = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--child", mode, str(model)]
        result = subprocess.run(argv, env=env, capture_output=True, timeout=60, check=False)
        (output / f"{mode}.stdout.log").write_bytes(result.stdout)
        (output / f"{mode}.stderr.log").write_bytes(result.stderr)
        cases.append({"mode": mode, "exit_code": result.returncode})
        (output / "RESULT.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf8")
        assert result.returncode == 0, (mode, result.stdout, result.stderr)
        body = json.loads(result.stdout.splitlines()[-1])
        assert body["status"] == "PASS" and body["GIL"] is False
    print(json.dumps({"status": "PASS", "cases": cases}))


if __name__ == "__main__":
    main()
