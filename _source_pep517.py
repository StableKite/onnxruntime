"""Build the normal CPU wheel with the upstream ONNX Runtime build driver."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import TypedDict, cast

ROOT = Path(__file__).resolve().parent


class _Installation(TypedDict):
    installationVersion: str


class _Generator(TypedDict):
    name: str


class _Capabilities(TypedDict):
    generators: list[_Generator]


def get_requires_for_build_wheel(config_settings: dict[str, object] | None = None) -> list[str]:
    return ["cmake>=4.2", "ninja", "numpy>=2", "setuptools>=77", "wheel", "packaging", "flatbuffers", "psutil", "sympy"]


def _generator(cmake: str) -> str:
    if sys.platform != "win32":
        return "Ninja"
    installer = Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
    vswhere = installer / "Microsoft Visual Studio/Installer/vswhere.exe"
    installations = cast(
        list[_Installation],
        json.loads(
            subprocess.check_output(
                [
                    str(vswhere),
                    "-latest",
                    "-products",
                    "*",
                    "-requires",
                    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                    "-format",
                    "json",
                ],
                text=True,
            )
        ),
    )
    if not installations:
        raise RuntimeError("Visual Studio C++ build tools are required for a Windows source build")
    major = installations[0]["installationVersion"].split(".")[0]
    capabilities = cast(_Capabilities, json.loads(subprocess.check_output([cmake, "-E", "capabilities"], text=True)))
    generator = next(
        (row["name"] for row in capabilities["generators"] if row["name"].startswith(f"Visual Studio {major} ")), None
    )
    if generator is None:
        raise RuntimeError("CMake does not support the installed Visual Studio version")
    return generator


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, object] | None = None,
    metadata_directory: str | None = None,
) -> str:
    if config_settings:
        raise ValueError("Use tools/ci_build/build.py for custom execution-provider or compiler configurations")
    cmake = shutil.which("cmake")
    if cmake is None:
        raise RuntimeError("The declared CMake build dependency is unavailable")
    destination = Path(wheel_directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    argv = [
        sys.executable,
        str(ROOT / "tools/ci_build/build.py"),
        "--config",
        "Release",
        "--parallel",
        "8",
        "--update",
        "--build",
        "--build_wheel",
        "--skip_pip_install",
        "--cmake_path",
        cmake,
        "--cmake_generator",
        _generator(cmake),
    ]
    if sys.platform == "win32":
        # Keep ambient vcpkg integration and reusable compiler workers out of
        # this temporary build; no machine or user settings are modified.
        env.pop("CMAKE_TOOLCHAIN_FILE", None)
        env["MSBUILDDISABLENODEREUSE"] = "1"
        argv += [
            "--cmake_extra_defines",
            "CMAKE_VS_GLOBALS=VcpkgEnabled=false;EnableClServerMode=false;UseMultiToolTask=false",
        ]
        architecture = {"win-arm64": "--arm64", "win32": "--x86", "win-arm64ec": "--arm64ec"}.get(
            sysconfig.get_platform()
        )
        if architecture:
            argv.append(architecture)
    with tempfile.TemporaryDirectory(prefix="ort-") as temporary:
        build = Path(temporary)
        subprocess.run([*argv, "--build_dir", str(build)], cwd=ROOT, env=env, check=True)
        wheels = list(build.glob("Release/**/dist/onnxruntime-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"Expected one upstream CPU wheel, found {len(wheels)}")
        shutil.copyfile(wheels[0], destination / wheels[0].name)
        return wheels[0].name
