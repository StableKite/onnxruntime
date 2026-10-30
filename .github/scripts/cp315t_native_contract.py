"""Real CPU inference, IO binding, worker callbacks and shared-session reads."""

import concurrent.futures
import importlib
import json
import queue
import sys
import threading
from pathlib import Path

assert not sys._is_gil_enabled()
np = importlib.import_module("numpy")
ort = importlib.import_module("onnxruntime")

assert not sys._is_gil_enabled()
options = ort.SessionOptions()
options.intra_op_num_threads = 2
options.inter_op_num_threads = 2
session = ort.InferenceSession(str(Path(sys.argv[1]).resolve(strict=True)), options, providers=["CPUExecutionProvider"])
assert session.get_providers() == ["CPUExecutionProvider"]
assert session.get_inputs()[0].name == "x"
assert session.get_outputs()[0].name == "y"
weights = np.array([[2, 3], [5, 7]], dtype=np.float32)
bias = np.array([11, 13], dtype=np.float32)
inputs = np.array([[1, 2], [3, 4]], dtype=np.float32)
expected = inputs @ weights + bias
np.testing.assert_array_equal(session.run(["y"], {"x": inputs})[0], expected)

binding = session.io_binding()
binding.bind_cpu_input("x", inputs)
binding.bind_output("y", "cpu")
session.run_with_iobinding(binding)
np.testing.assert_array_equal(binding.copy_outputs_to_cpu()[0], expected)
ort_inputs = ort.OrtValue.ortvalue_from_numpy(inputs)
np.testing.assert_array_equal(session.run_with_ort_values(["y"], {"x": ort_inputs})[0].numpy(), expected)

completed = threading.Event()
callback_results = queue.SimpleQueue()


def callback(outputs, user_data, error):
    callback_results.put((outputs, user_data, error, sys._is_gil_enabled(), threading.get_native_id()))
    completed.set()


session.run_async(["y"], {"x": inputs}, callback, "owned-callback")
assert completed.wait(30)
outputs, user_data, error, callback_gil, callback_thread = callback_results.get_nowait()
assert not error and user_data == "owned-callback" and not callback_gil
np.testing.assert_array_equal(outputs[0], expected)


def worker(seed):
    for number in range(64):
        owned = np.full((3, 2), seed * 64 + number, dtype=np.float32)
        np.testing.assert_array_equal(session.run(["y"], {"x": owned})[0], owned @ weights + bias)
    return 64


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    assert sum(pool.map(worker, range(8))) == 512
assert not sys._is_gil_enabled()
print(
    json.dumps(
        {
            "status": "PASS",
            "python": sys.version,
            "GIL": False,
            "version": ort.__version__,
            "providers": session.get_providers(),
            "native_module": sys.modules["onnxruntime.capi.onnxruntime_pybind11_state"].__file__,
            "threaded_inferences": 512,
            "callback_native_thread": callback_thread,
            "callback_GIL": callback_gil,
            "IO_binding": "PASS",
            "OrtValue": "PASS",
        }
    )
)
