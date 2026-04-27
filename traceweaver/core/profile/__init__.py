"""
Layer 1 — Profile (scene package). See docs/design/platform-v2.md §4 Layer 1.

A Profile packages everything that makes one analysis scene reproducible:
  - how to ingest its source (source_config)
  - the LLM system prompt and max_rounds
  - its response schema (diagnosis shape)
  - declared knowledge files
  - declared tools (deferred to a later M)

The loader scans local directories so users can drop a profile into
`~/.traceweaver/profiles/<name>/` without packaging.
"""

from traceweaver.core.profile.base import Profile, ProfileLLMConfig, ProfileKnowledgeItem
from traceweaver.core.profile.loader import (
    SOURCE_BUILTIN,
    SOURCE_ENTRY_POINT,
    SOURCE_LOCAL_DIR,
    ProfileLoader,
    ProfileSource,
    find_profile_dirs,
)
from traceweaver.core.profile.yaml_loader import load_profile_from_dir

__all__ = [
    "Profile",
    "ProfileKnowledgeItem",
    "ProfileLLMConfig",
    "ProfileLoader",
    "ProfileSource",
    "SOURCE_BUILTIN",
    "SOURCE_ENTRY_POINT",
    "SOURCE_LOCAL_DIR",
    "find_profile_dirs",
    "load_profile_from_dir",
]
