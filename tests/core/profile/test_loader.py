"""Tests for ProfileLoader discovery + collision rules."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from traceweaver.core.profile import ProfileLoader, find_profile_dirs


def _make_profile_dir(base: Path, name: str) -> Path:
    pdir = base / name
    (pdir / "prompts").mkdir(parents=True)
    (pdir / "prompts" / "system.md").write_text("p", encoding="utf-8")
    (pdir / "profile.yaml").write_text(
        f"name: {name}\nllm:\n  system_prompt_file: prompts/system.md\n",
        encoding="utf-8",
    )
    return pdir


def test_search_path_includes_env_and_home(tmp_path) -> None:
    env_dir = tmp_path / "env"
    home_dir = tmp_path / "home"
    env_dir.mkdir()
    (home_dir / ".traceweaver" / "profiles").mkdir(parents=True)
    dirs = find_profile_dirs(
        env={"TRACEWEAVER_PROFILES_PATH": str(env_dir)},
        home_dir=home_dir,
    )
    assert env_dir in dirs
    assert (home_dir / ".traceweaver" / "profiles") in dirs
    assert dirs.index(env_dir) < dirs.index(home_dir / ".traceweaver" / "profiles")


def test_search_path_respects_multiple_entries(tmp_path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    joined = os.pathsep.join([str(a), str(b)])
    dirs = find_profile_dirs(
        env={"TRACEWEAVER_PROFILES_PATH": joined},
        home_dir=tmp_path / "no-home",
    )
    assert a in dirs and b in dirs


def test_discover_and_load(tmp_path) -> None:
    _make_profile_dir(tmp_path, "demo")
    loader = ProfileLoader(extra_dirs=[tmp_path], home_dir=tmp_path / "no-home")
    assert loader.discover().keys() == {"demo"}
    prof = loader.load("demo")
    assert prof.name == "demo"


def test_load_unknown(tmp_path) -> None:
    loader = ProfileLoader(extra_dirs=[tmp_path], home_dir=tmp_path / "no-home")
    with pytest.raises(KeyError, match="profile not found"):
        loader.load("missing")


def test_collision_earlier_wins(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _make_profile_dir(first, "demo")
    dup = _make_profile_dir(second, "demo")
    # sanity: both have a profile.yaml
    assert (dup / "profile.yaml").exists()
    loader = ProfileLoader(
        extra_dirs=[first, second],
        home_dir=tmp_path / "no-home",
    )
    found = loader.discover()
    assert found["demo"].parent == first


def test_name_mismatch_raises(tmp_path) -> None:
    pdir = tmp_path / "demo"
    (pdir / "prompts").mkdir(parents=True)
    (pdir / "prompts" / "system.md").write_text("p", encoding="utf-8")
    (pdir / "profile.yaml").write_text(
        "name: wrong\nllm:\n  system_prompt_file: prompts/system.md\n",
        encoding="utf-8",
    )
    loader = ProfileLoader(extra_dirs=[tmp_path], home_dir=tmp_path / "no-home")
    with pytest.raises(ValueError, match="inconsistent name"):
        loader.load("demo")
