"""
Profile discovery loader.

Scans the local directories listed in platform-v2.md §4 Layer 1:

1. `$TRACEWEAVER_PROFILES_PATH` (colon/semicolon-separated on *nix/Windows)
2. `~/.traceweaver/profiles/`
3. Any directories passed explicitly to `ProfileLoader(extra_dirs=...)`.

Each subdirectory that contains a `profile.yaml` is treated as a profile.
On name collision the *earlier* search path wins (lets users override a
system profile by copying it into their home).

Loading is lazy: listing + discovery is cheap; actual parsing happens
on `load(name)`. pip-packaged profiles (entry_points) are M4+.
"""

from __future__ import annotations

import os
from pathlib import Path

from traceweaver.core.profile.base import Profile
from traceweaver.core.profile.yaml_loader import load_profile_from_dir


_ENV_VAR = "TRACEWEAVER_PROFILES_PATH"
_DEFAULT_USER_DIR = Path.home() / ".traceweaver" / "profiles"


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


class ProfileLoader:
    def __init__(
        self,
        *,
        extra_dirs: list[Path] | None = None,
        env: dict[str, str] | None = None,
        home_dir: Path | None = None,
    ) -> None:
        self._dirs: list[Path] = find_profile_dirs(
            extra_dirs=extra_dirs, env=env, home_dir=home_dir
        )

    def search_path(self) -> list[Path]:
        return list(self._dirs)

    def discover(self) -> dict[str, Path]:
        """
        Map `profile name (= directory name)` -> absolute path.

        The name key is the directory basename, matching v1's convention
        and what users type on the CLI. The profile's `name` field inside
        `profile.yaml` must match, but that check happens at load time.
        """
        found: dict[str, Path] = {}
        for root in self._dirs:
            for sub in sorted(root.iterdir()):
                if not sub.is_dir():
                    continue
                if not (sub / "profile.yaml").is_file():
                    continue
                if sub.name in found:
                    continue
                found[sub.name] = sub
        return found

    def load(self, name: str) -> Profile:
        available = self.discover()
        if name not in available:
            raise KeyError(
                f"profile not found: {name!r} "
                f"(known: {sorted(available.keys())}; "
                f"searched: {[str(d) for d in self._dirs]})"
            )
        profile = load_profile_from_dir(available[name])
        if profile.name != name:
            raise ValueError(
                f"profile directory {name!r} declares inconsistent name "
                f"{profile.name!r} in profile.yaml"
            )
        return profile


__all__ = ["ProfileLoader", "find_profile_dirs"]
