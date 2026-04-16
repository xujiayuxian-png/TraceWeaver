import pytest

from pathlib import Path

from traceweaver import investigate_capture

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pcap"


class _StubLLMProvider:
    class _Config:
        model = "stub/investigation-planner"
        model_tier = "balanced"
        max_retries = 0

    def __init__(self) -> None:
        self.config = self._Config()

    def complete_json(self, system_prompt: str, user_prompt: str) -> dict:
        assert system_prompt
        assert user_prompt
        if "hypothesis_order" in user_prompt:
            return {
                "hypothesis_order": ["ran-1__amf-2:success-path"],
                "tool_sequence": ["frame_targeting", "protocol_drilldown", "signal_focus"],
                "stop_when": "stop_when_success_path_is_confirmed",
                "reasoning": "prefer targeted confirmation before broad tools",
            }
        if "termination_reconsideration_schema" in user_prompt:
            return {
                "status": "completed",
                "reason": "llm_confirmed_success_path",
                "confidence": "high",
                "next_actions": [
                    "review targeted confirmation frames before closing the investigation",
                    "archive the success-path evidence set",
                ],
                "reasoning": "the selected tools already provide enough evidence to stop",
            }
        return {
            "verdict": "OK",
            "failure_point": None,
            "root_cause": None,
            "confidence": "high",
            "evidence": [{"frame_number": 468, "description": "initial context setup confirms protected registration success path"}],
            "suggestions": ["confirm success path with targeted frame review"],
            "limitations": [],
            "reasoning": "registration succeeded and planner should now optimize confirmation tools",
        }


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
    assert first_investigation.plan is not None
    assert first_investigation.steps
    assert first_investigation.hypotheses
    assert first_investigation.executed_tools
    assert first_investigation.tool_results
    assert first_investigation.termination is not None
    assert first_investigation.next_actions
    assert first_investigation.round_count >= 2
    assert "protocol_drilldown" in first_investigation.executed_tools
    assert "frame_targeting" in first_investigation.executed_tools

    first_diagnosis = result.diagnoses[0]
    phases = [item["phase"] for item in first_diagnosis.investigation_trace]
    assert phases[0] == "plan"
    assert "tool" in phases
    assert phases[-1] == "termination"


def test_investigate_capture_can_filter_scope_id() -> None:
    base = investigate_capture(
        FIXTURES_DIR / "01_registration_success.pcapng",
        profile="open5gs_5gc",
    )
    scope_id = base.investigations[0].scope_id

    filtered = investigate_capture(
        FIXTURES_DIR / "01_registration_success.pcapng",
        profile="open5gs_5gc",
        scope_id=scope_id,
    )

    assert filtered.selected_scope_id == scope_id
    assert filtered.scope_count == 1
    assert len(filtered.contexts) == 1
    assert len(filtered.investigations) == 1
    assert filtered.investigations[0].scope_id == scope_id


def test_investigation_planner_can_use_llm_for_tool_selection() -> None:
    result = investigate_capture(
        FIXTURES_DIR / "01_registration_success.pcapng",
        profile="open5gs_5gc",
        llm_provider=_StubLLMProvider(),
    )

    investigation = result.investigations[0]
    assert investigation.plan is not None
    assert investigation.plan.planning_source == "llm"
    assert investigation.plan.tool_sequence[0] == "frame_targeting"
    assert investigation.steps[0].details["planning_source"] == "llm"
    assert investigation.termination is not None
    assert investigation.termination.source == "llm"
    assert investigation.termination.reason == "llm_confirmed_success_path"
    assert investigation.termination.reasoning == "the selected tools already provide enough evidence to stop"
    assert investigation.next_actions[0] == "review targeted confirmation frames before closing the investigation"


def test_investigate_capture_invalid_scope_id_raises() -> None:
    with pytest.raises(ValueError, match="scope not found"):
        investigate_capture(
            FIXTURES_DIR / "01_registration_success.pcapng",
            profile="open5gs_5gc",
            scope_id="does-not-exist",
        )
