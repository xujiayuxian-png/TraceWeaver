from pathlib import Path

from traceweaver import investigate_capture

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


def test_investigate_capture_returns_contexts_and_investigations() -> None:
    result = investigate_capture(
        FIXTURES_DIR / "01_registration_success.pcapng",
        profile="open5gs_5gc",
    )

    assert result.profile_name == "open5gs_5gc"
    assert result.scope_count >= 1
    assert len(result.contexts) == len(result.investigations)
    assert len(result.diagnoses) == len(result.investigations)

    first_context = result.contexts[0]
    first_investigation = result.investigations[0]

    assert first_context.scope.scope_id == first_investigation.scope_id
    assert first_context.visibility is not None
    assert first_context.evidence
    assert first_investigation.steps
    assert first_investigation.hypotheses
    assert first_investigation.next_actions
