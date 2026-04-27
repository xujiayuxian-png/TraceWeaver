"""
Profile discovery loader.

Discovers profiles from three independent sources, in priority order:

1. **entry_points** advertised in installed Python distributions under
   the ``traceweaver.profiles`` group. This is how third-party pip
   packages register themselves; see
   ``docs/guides/python-packaging-profiles.md``.
2. **Built-in namespace** ``traceweaver.profiles.<name>`` — every
   subpackage of ``traceweaver/profiles/`` that ships a ``profile.yaml``
   counts. The reference Open5GS 5GC profile arrives via this path.
3. **Local directories** scanned in this order:

   * ``$TRACEWEAVER_PROFILES_PATH`` (``os.pathsep``-separated)
   * any directories passed via ``ProfileLoader(extra_dirs=...)``
   * ``~/.traceweaver/profiles/``

On name collision the *earlier* source wins (so a user-installed
package overrides a built-in, which in turn overrides a stray copy
in ``~/.traceweaver``). When entry_points or local dirs override a
built-in, a one-line warning is emitted to stderr — set
``TRACEWEAVER_QUIET_PROFILE_OVERRIDE=1`` to silence it.

Loading is lazy: listing + discovery is cheap; actual YAML parsing
happens on ``load(name)``.
"""

from __future__ import annotations

import importlib
import os
import sys
from importlib.metadata import entry_points
from pathlib import Path

from traceweaver.core.profile.base import Profile
from traceweaver.core.profile.yaml_loader import load_profile_from_dir


_ENV_VAR = "TRACEWEAVER_PROFILES_PATH"
_QUIET_VAR = "TRACEWEAVER_QUIET_PROFILE_OVERRIDE"
_DEFAULT_USER_DIR = Path.home() / ".traceweaver" / "profiles"
_ENTRY_POINT_GROUP = "traceweaver.profiles"

# Discovery source labels, ordered by priority (first wins).
SOURCE_ENTRY_POINT = "entry_point"
SOURCE_BUILTIN = "builtin"
SOURCE_LOCAL_DIR = "local_dir"


def find_profile_dirs(
    *,
    extra_dirs: list[Path] | None = None,
    env: dict[str, str] | None = None,
    home_dir: Path | None = None,
) -> list[Path]:
    """
    Resolve the ordered list of directories to scan. Exposed so tests
    can drive it with a fake environment without touching real $HOME.
    """
    env = env if env is not None else dict(os.environ)
    home = home_dir or (Path(env["HOME"]) if "HOME" in env else Path.home())

    dirs: list[Path] = []
    env_val = env.get(_ENV_VAR, "")
    if env_val:
        for token in env_val.split(os.pathsep):
            token = token.strip()
            if token:
                dirs.append(Path(token).resolve())
    if extra_dirs:
        for d in extra_dirs:
            dirs.append(Path(d).resolve())
    dirs.append((home / ".traceweaver" / "profiles").resolve())

    seen: set[Path] = set()
    ordered: list[Path] = []
    for d in dirs:
        if d in seen:
            continue
        seen.add(d)
        if d.is_dir():
            ordered.append(d)
    return ordered


def _iter_entry_point_profiles(
    *,
    eps_factory=None,
    on_warning=None,
) -> dict[str, Path]:
    """
    Discover profiles registered via ``[project.entry-points."traceweaver.profiles"]``.

    `eps_factory` is injected by tests; default uses the real metadata.
    The accepted entry-point value forms are:

    * ``"<module>"`` — the module's package directory is the profile dir
    * ``"<module>:profile.yaml"`` — same; the suffix is informational and
      currently ignored (kept for forward compatibility with future
      multi-profile-per-module layouts)
    """
    factory = eps_factory or (lambda: entry_points(group=_ENTRY_POINT_GROUP))
    warn = on_warning or _stderr_warning
    found: dict[str, Path] = {}
    try:
        eps = factory()
    except Exception as exc:  # importlib.metadata can fail on broken envs
        warn(f"profile discovery: entry_points lookup failed: {exc}")
        return {}
    for ep in eps:
        module_path = (ep.value or "").split(":", 1)[0].strip()
        if not module_path:
            warn(f"profile entry_point {ep.name!r}: empty module path")
            continue
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            warn(
                f"profile entry_point {ep.name!r}: cannot import "
                f"{module_path!r}: {exc}"
            )
            continue
        mod_file = getattr(mod, "__file__", None)
        if mod_file is None:
            warn(
                f"profile entry_point {ep.name!r}: module {module_path!r} "
                f"has no __file__ (namespace package?)"
            )
            continue
        profile_dir = Path(mod_file).resolve().parent
        if not (profile_dir / "profile.yaml").is_file():
            warn(
                f"profile entry_point {ep.name!r}: no profile.yaml in "
                f"{profile_dir}"
            )
            continue
        if ep.name in found:
            # Multiple distributions registered the same profile name.
            warn(
                f"profile entry_point {ep.name!r}: duplicate; ignoring "
                f"{profile_dir} (already have {found[ep.name]})"
            )
            continue
        found[ep.name] = profile_dir
    return found


def _iter_builtin_namespace_profiles() -> dict[str, Path]:
    """
    List every subpackage of ``traceweaver.profiles`` that ships a
    ``profile.yaml`` next to its ``__init__.py``.
    """
    try:
        ns = importlib.import_module("traceweaver.profiles")
    except ImportError:
        return {}
    found: dict[str, Path] = {}
    for root in getattr(ns, "__path__", []):
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        for sub in sorted(root_path.iterdir()):
            if not sub.is_dir():
                continue
            if not (sub / "profile.yaml").is_file():
                continue
            if sub.name in found:
                continue
            found[sub.name] = sub.resolve()
    return found


def _iter_local_dir_profiles(dirs: list[Path]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for root in dirs:
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            if not (sub / "profile.yaml").is_file():
                continue
            if sub.name in found:
                continue
            found[sub.name] = sub
    return found


def _stderr_warning(msg: str) -> None:
    if os.environ.get(_QUIET_VAR):
        return
    print(f"[traceweaver] {msg}", file=sys.stderr)


class ProfileLoader:
    def __init__(
        self,
        *,
        extra_dirs: list[Path] | None = None,
        env: dict[str, str] | None = None,
        home_dir: Path | None = None,
        eps_factory=None,
        on_warning=None,
    ) -> None:
        self._dirs: list[Path] = find_profile_dirs(
            extra_dirs=extra_dirs, env=env, home_dir=home_dir
        )
        self._eps_factory = eps_factory
        self._on_warning = on_warning or _stderr_warning

    def search_path(self) -> list[Path]:
        return list(self._dirs)

    def discover(self) -> dict[str, Path]:
        """
        Flat map of `profile name -> absolute path`, with sources merged
        in priority order (entry_points > builtin namespace > local dirs).
        Use `discover_with_source()` if you also need the origin label.
        """
        return {n: src.path for n, src in self.discover_with_source().items()}

    def discover_with_source(self) -> dict[str, "ProfileSource"]:
        """
        Same as `discover()` but tags every entry with its origin label
        (one of `SOURCE_ENTRY_POINT`, `SOURCE_BUILTIN`, `SOURCE_LOCAL_DIR`).
        """
        ep_profiles = _iter_entry_point_profiles(
            eps_factory=self._eps_factory,
            on_warning=self._on_warning,
        )
        builtin_profiles = _iter_builtin_namespace_profiles()
        local_profiles = _iter_local_dir_profiles(self._dirs)

        merged: dict[str, ProfileSource] = {}
        for name, path in ep_profiles.items():
            merged[name] = ProfileSource(name=name, path=path, origin=SOURCE_ENTRY_POINT)
        for name, path in builtin_profiles.items():
            if name in merged:
                self._on_warning(
                    f"profile {name!r}: entry_point at {merged[name].path} "
                    f"shadows built-in at {path}"
                )
                continue
            merged[name] = ProfileSource(name=name, path=path, origin=SOURCE_BUILTIN)
        for name, path in local_profiles.items():
            if name in merged:
                existing = merged[name]
                if existing.origin == SOURCE_BUILTIN:
                    self._on_warning(
                        f"profile {name!r}: local dir {path} shadows "
                        f"built-in at {existing.path}"
                    )
                # entry_point already wins silently — no warning needed
                # since user-installed > built-in is the documented order.
                continue
            merged[name] = ProfileSource(name=name, path=path, origin=SOURCE_LOCAL_DIR)
        return merged

    def load(self, name: str) -> Profile:
        available = self.discover()
        if name not in available:
            raise KeyError(
                f"profile not found: {name!r} "
                f"(known: {sorted(available.keys())}; "
                f"searched local dirs: {[str(d) for d in self._dirs]})"
            )
        profile = load_profile_from_dir(available[name])
        if profile.name != name:
            raise ValueError(
                f"profile {name!r} declares inconsistent name "
                f"{profile.name!r} in profile.yaml"
            )
        return profile


class ProfileSource:
    """A discovered profile entry tagged with where it came from."""

    __slots__ = ("name", "path", "origin")

    def __init__(self, *, name: str, path: Path, origin: str) -> None:
        self.name = name
        self.path = path
        self.origin = origin

    def __repr__(self) -> str:  # pragma: no cover — debugging only
        return f"ProfileSource(name={self.name!r}, origin={self.origin!r}, path={self.path!s})"


__all__ = [
    "ProfileLoader",
    "ProfileSource",
    "SOURCE_BUILTIN",
    "SOURCE_ENTRY_POINT",
    "SOURCE_LOCAL_DIR",
    "find_profile_dirs",
]
