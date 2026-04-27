# tw-test-external-profile

A throw-away **fixture package** that exists for one purpose: prove that
TraceWeaver's `traceweaver.profiles` entry_points discovery actually
works end-to-end when a profile is delivered as a normal `pip install`-able
distribution.

This is the package referenced from `scripts/smoke_external_profile.py`.

## Layout

```
tests/fixtures/external_profile_pkg/
├── pyproject.toml                            # entry_points + force-include
├── src/
│   └── tw_test_external_profile/
│       ├── __init__.py                       # empty
│       ├── profile.yaml                      # name: tw_test_external
│       └── prompts/
│           └── system.md                     # placeholder
└── README.md
```

## How the smoke script uses it

```powershell
.venv\Scripts\pip install -e tests\fixtures\external_profile_pkg\
.venv\Scripts\traceweaver profile list
# → tw_test_external should appear with origin = "entry_point"
.venv\Scripts\pip uninstall tw-test-external-profile -y
```

You shouldn't need to run any of that by hand; `scripts/smoke_external_profile.py`
wraps it.

## Why a fixture package and not just a unit test?

Unit tests in `tests/core/profile/test_loader.py` already inject fake
entry_points via dependency injection — they cover the `ProfileLoader`
contract. What they **can't** catch is real packaging breakage: wheel
metadata, `force-include` for non-.py files, `entry_points.txt`
generation by hatchling, etc. The fixture + smoke script catches that
class of bugs without us having to push anything to PyPI.
