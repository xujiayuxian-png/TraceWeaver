from argparse import Namespace

from traceweaver.cli import _build_options


def test_build_options_maps_limit_to_scope_limit() -> None:
    options = _build_options(
        Namespace(
            display_filter=None,
            decode_as=[],
            limit=2,
            record_limit=7,
        )
    )

    assert options.scope_limit == 2
    assert options.record_limit == 7
