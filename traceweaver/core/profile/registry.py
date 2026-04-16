from __future__ import annotations

from traceweaver.core.analysis.result import ProfileDescriptor
from traceweaver.core.profile.base import AnalysisProfile

_PROFILES: dict[str, AnalysisProfile] = {}
_BUILTINS_LOADED = False


def register_profile(profile: AnalysisProfile) -> None:
    _PROFILES[profile.name] = profile


def _ensure_builtins_loaded() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    import traceweaver.profiles  # noqa: F401

    _BUILTINS_LOADED = True


def get_profile(name: str) -> AnalysisProfile:
    _ensure_builtins_loaded()
    try:
        return _PROFILES[name]
    except KeyError as exc:
        available = ", ".join(sorted(_PROFILES)) or "<none>"
        raise ValueError(f"unknown profile '{name}', available: {available}") from exc


def list_profile_descriptors() -> list[ProfileDescriptor]:
    _ensure_builtins_loaded()
    return [
        ProfileDescriptor(name=profile.name, description=getattr(profile, "description", ""))
        for profile in sorted(_PROFILES.values(), key=lambda item: item.name)
    ]
