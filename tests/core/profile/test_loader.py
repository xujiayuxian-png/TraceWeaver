"""Tests for ProfileLoader discovery + collision rules."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from traceweaver.core.profile import (
    SOURCE_BUILTIN,
    SOURCE_ENTRY_POINT,
    SOURCE_LOCAL_DIR,
    ProfileLoader,
    find_profile_dirs,
)


@dataclass
class _FakeEP:
    name: str
    value: str


def _no_op_warn(_msg: str) -> None:
    """Test default that swallows discovery warnings."""


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
    loader = ProfileLoader(
        extra_dirs=[tmp_path],
        home_dir=tmp_path / "no-home",
        eps_factory=lambda: [],
        on_warning=_no_op_warn,
    )
    discovered = loader.discover()
    # `demo` from local dir is found; built-in profiles (e.g. open5gs_5gc)
    # may also be present in the same map -- the loader merges all sources.
    assert "demo" in discovered
    prof = loader.load("demo")
    assert prof.name == "demo"


def test_load_unknown(tmp_path) -> None:
    loader = ProfileLoader(
        extra_dirs=[tmp_path],
        home_dir=tmp_path / "no-home",
        eps_factory=lambda: [],
        on_warning=_no_op_warn,
    )
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
        eps_factory=lambda: [],
        on_warning=_no_op_warn,
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
    loader = ProfileLoader(
        extra_dirs=[tmp_path],
        home_dir=tmp_path / "no-home",
        eps_factory=lambda: [],
        on_warning=_no_op_warn,
    )
    with pytest.raises(ValueError, match="inconsistent name"):
        loader.load("demo")


# ---- entry_points discovery -----------------------------------------


def test_builtin_namespace_profile_visible() -> None:
    """
    Sanity: the in-tree open5gs_5gc profile must be discoverable purely
    via the built-in namespace, even with no entry_points and no local
    dirs configured.
    """
    loader = ProfileLoader(
        extra_dirs=[],
        home_dir=Path("/non-existent-home"),
        env={},
        eps_factory=lambda: [],
        on_warning=_no_op_warn,
    )
    sources = loader.discover_with_source()
    assert "open5gs_5gc" in sources
    assert sources["open5gs_5gc"].origin == SOURCE_BUILTIN


def test_entry_point_profile_discovered(tmp_path) -> None:
    # Build a tiny package on disk that imports cleanly.
    pkg_root = tmp_path / "fake_ep_pkg"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    (pkg_root / "prompts").mkdir()
    (pkg_root / "prompts" / "system.md").write_text("x", encoding="utf-8")
    (pkg_root / "profile.yaml").write_text(
        "name: fake_ep\nllm:\n  system_prompt_file: prompts/system.md\n",
        encoding="utf-8",
    )

    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        loader = ProfileLoader(
            extra_dirs=[],
            home_dir=tmp_path / "no-home",
            env={},
            eps_factory=lambda: [_FakeEP(name="fake_ep", value="fake_ep_pkg")],
            on_warning=_no_op_warn,
        )
        sources = loader.discover_with_source()
        assert "fake_ep" in sources
        assert sources["fake_ep"].origin == SOURCE_ENTRY_POINT
        prof = loader.load("fake_ep")
        assert prof.name == "fake_ep"
    finally:
        sys.path.remove(str(tmp_path))
        # Unpoison sys.modules so other tests aren't affected.
        for mod in list(sys.modules):
            if mod == "fake_ep_pkg" or mod.startswith("fake_ep_pkg."):
                del sys.modules[mod]


def test_entry_point_priority_over_builtin(tmp_path) -> None:
    """
    When an entry_point and a built-in expose the same profile name,
    the entry_point wins and a warning is emitted.
    """
    # Build a fake package that pretends to be `open5gs_5gc`.
    pkg_root = tmp_path / "impostor_pkg"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    (pkg_root / "prompts").mkdir()
    (pkg_root / "prompts" / "system.md").write_text("x", encoding="utf-8")
    (pkg_root / "profile.yaml").write_text(
        "name: open5gs_5gc\nllm:\n  system_prompt_file: prompts/system.md\n",
        encoding="utf-8",
    )

    warnings: list[str] = []

    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        loader = ProfileLoader(
            extra_dirs=[],
            home_dir=tmp_path / "no-home",
            env={},
            eps_factory=lambda: [
                _FakeEP(name="open5gs_5gc", value="impostor_pkg"),
            ],
            on_warning=warnings.append,
        )
        sources = loader.discover_with_source()
        assert sources["open5gs_5gc"].origin == SOURCE_ENTRY_POINT
        assert sources["open5gs_5gc"].path == pkg_root.resolve()
        assert any("shadows built-in" in w for w in warnings)
    finally:
        sys.path.remove(str(tmp_path))
        for mod in list(sys.modules):
            if mod == "impostor_pkg" or mod.startswith("impostor_pkg."):
                del sys.modules[mod]


def test_entry_point_value_with_yaml_suffix(tmp_path) -> None:
    """
    Documented entry_point form `'<module>:profile.yaml'` must be
    accepted: the suffix is informational and ignored.
    """
    pkg_root = tmp_path / "suffix_pkg"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    (pkg_root / "prompts").mkdir()
    (pkg_root / "prompts" / "system.md").write_text("x", encoding="utf-8")
    (pkg_root / "profile.yaml").write_text(
        "name: suffixed\nllm:\n  system_prompt_file: prompts/system.md\n",
        encoding="utf-8",
    )

    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        loader = ProfileLoader(
            extra_dirs=[],
            home_dir=tmp_path / "no-home",
            env={},
            eps_factory=lambda: [
                _FakeEP(name="suffixed", value="suffix_pkg:profile.yaml"),
            ],
            on_warning=_no_op_warn,
        )
        sources = loader.discover_with_source()
        assert "suffixed" in sources
        assert sources["suffixed"].origin == SOURCE_ENTRY_POINT
    finally:
        sys.path.remove(str(tmp_path))
        for mod in list(sys.modules):
            if mod == "suffix_pkg" or mod.startswith("suffix_pkg."):
                del sys.modules[mod]


def test_entry_point_broken_module_warns(tmp_path) -> None:
    """
    A broken entry_point (module won't import / wrong path) must not
    abort discovery; it must emit a warning and skip.
    """
    warnings: list[str] = []
    loader = ProfileLoader(
        extra_dirs=[],
        home_dir=tmp_path / "no-home",
        env={},
        eps_factory=lambda: [
            _FakeEP(name="broken", value="this_module_does_not_exist_xyz"),
        ],
        on_warning=warnings.append,
    )
    sources = loader.discover_with_source()
    assert "broken" not in sources
    assert any("cannot import" in w for w in warnings)


def test_entry_point_missing_yaml_warns(tmp_path) -> None:
    pkg_root = tmp_path / "empty_pkg"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    # NB: no profile.yaml here.

    warnings: list[str] = []
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        loader = ProfileLoader(
            extra_dirs=[],
            home_dir=tmp_path / "no-home",
            env={},
            eps_factory=lambda: [
                _FakeEP(name="empty", value="empty_pkg"),
            ],
            on_warning=warnings.append,
        )
        sources = loader.discover_with_source()
        assert "empty" not in sources
        assert any("no profile.yaml" in w for w in warnings)
    finally:
        sys.path.remove(str(tmp_path))
        for mod in list(sys.modules):
            if mod == "empty_pkg" or mod.startswith("empty_pkg."):
                del sys.modules[mod]


def test_local_dir_does_not_shadow_entry_point_silently(tmp_path) -> None:
    """
    When a local dir profile shares a name with an entry_point profile,
    the entry_point keeps winning (per documented priority) and we do
    NOT spam a warning -- user-installed wins is the intended order.
    """
    pkg_root = tmp_path / "winner_pkg"
    pkg_root.mkdir()
    (pkg_root / "__init__.py").write_text("", encoding="utf-8")
    (pkg_root / "prompts").mkdir()
    (pkg_root / "prompts" / "system.md").write_text("x", encoding="utf-8")
    (pkg_root / "profile.yaml").write_text(
        "name: dup\nllm:\n  system_prompt_file: prompts/system.md\n",
        encoding="utf-8",
    )

    local_root = tmp_path / "local"
    _make_profile_dir(local_root, "dup")

    warnings: list[str] = []
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        loader = ProfileLoader(
            extra_dirs=[local_root],
            home_dir=tmp_path / "no-home",
            env={},
            eps_factory=lambda: [
                _FakeEP(name="dup", value="winner_pkg"),
            ],
            on_warning=warnings.append,
        )
        sources = loader.discover_with_source()
        assert sources["dup"].origin == SOURCE_ENTRY_POINT
        assert not any("shadow" in w for w in warnings)
    finally:
        sys.path.remove(str(tmp_path))
        for mod in list(sys.modules):
            if mod == "winner_pkg" or mod.startswith("winner_pkg."):
                del sys.modules[mod]
