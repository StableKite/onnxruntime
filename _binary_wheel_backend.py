"""Deliver qualified CPU wheels only for their exact, unchanged native source."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import TypedDict, cast

import _source_pep517

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent


class Artifact(TypedDict):
    filename: str
    url: str
    sha256: str


class Manifest(TypedDict):
    source_commit: str
    source_project: str
    delivery_paths: list[str]
    delivery_source_hashes: dict[str, str]
    minimum_glibc: list[int]
    artifacts: dict[str, Artifact]


def _source_project() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf8"))
    data.pop("build-system", None)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _asset(config_settings: dict[str, object] | None = None) -> Artifact | None:
    if (
        config_settings
        or sys.version_info[:2] != (3, 15)
        or not sysconfig.get_config_var("Py_GIL_DISABLED")
        or sysconfig.get_config_var("Py_DEBUG")
    ):
        return None
    if any(os.environ.get(name) for name in ("CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "CC", "CXX", "CMAKE_ARGS")):
        return None
    if sysconfig.get_platform() == "win-amd64":
        target = "win_amd64"
    elif sys.platform == "linux" and platform.machine() == "x86_64":
        target = "linux_x86_64"
    else:
        return None
    data = cast(Manifest, json.loads((ROOT / "binary_wheels.json").read_text("utf8")))
    if target == "linux_x86_64":
        libc, version = platform.libc_ver()
        if libc != "glibc" or tuple(map(int, version.split("."))) < tuple(data["minimum_glibc"]):
            return None
    artifact = data["artifacts"].get(target)
    if artifact is None:
        return None
    for name, digest in data["delivery_source_hashes"].items():
        path = ROOT / name
        if not path.is_file():
            return None
        content = path.read_bytes()
        if path.suffix in {".py", ".md", ".toml", ".json", ".yml"} or path.name == ".gitignore":
            content = content.replace(b"\r\n", b"\n")
        if hashlib.sha256(content).hexdigest() != digest:
            return None
    if _source_project() != data["source_project"]:
        return None
    exclusions = [".", *[":(exclude)" + name for name in data["delivery_paths"]]]
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--quiet", data["source_commit"], "--", *exclusions],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if result.returncode:
            return None
        untracked = subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard"],
            text=True,
            timeout=30,
        ).splitlines()
        if any(
            name not in data["delivery_paths"]
            and not (
                name.startswith(("__pycache__/_binary_wheel_backend.", "__pycache__/_source_pep517."))
                and name.endswith(".pyc")
            )
            for name in untracked
        ):
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return artifact


def get_requires_for_build_wheel(config_settings: dict[str, object] | None = None) -> list[str]:
    if _asset(config_settings) is not None:
        return ["pip"]
    return _source_pep517.get_requires_for_build_wheel(config_settings)


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, object] | None = None,
    metadata_directory: str | None = None,
) -> str:
    artifact = _asset(config_settings)
    if artifact is None:
        return _source_pep517.build_wheel(wheel_directory, config_settings, metadata_directory)
    destination = Path(wheel_directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--no-deps",
            "--only-binary=:all:",
            "--dest",
            str(destination),
            artifact["url"] + "#sha256=" + artifact["sha256"],
        ],
        check=True,
    )
    downloaded = destination / artifact["filename"]
    if hashlib.sha256(downloaded.read_bytes()).hexdigest() != artifact["sha256"]:
        raise RuntimeError("Downloaded wheel SHA256 does not match the qualified artifact")
    return downloaded.name
