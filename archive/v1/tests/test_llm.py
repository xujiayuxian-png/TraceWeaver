from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from traceweaver import analyze_capture
from traceweaver.llm.output import LLMDiagnosisOutput, parse_llm_diagnosis
from traceweaver.llm.prompts import build_diagnosis_prompt, format_signals, format_timeline
from traceweaver.llm.provider import LLMConfig, LLMProvider, _extract_json, _should_disable_thinking, infer_model_tier
from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal
from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession

FIXTURES = Path(__file__).parent / "fixtures" / "pcap"


def _analyze_capture(pcap_path: str | Path, *, llm_provider=None):
    return analyze_capture(str(pcap_path), profile="open5gs_5gc", llm_provider=llm_provider)


class TestModelTierInference:
    def test_large_models(self) -> None:
        assert infer_model_tier("gpt-4o") == "large"
        assert infer_model_tier("claude-3.5-sonnet") == "large"
        assert infer_model_tier("qwen2.5:72b") == "large"

    def test_medium_models(self) -> None:
        assert infer_model_tier("gpt-4o-mini") == "medium"
        assert infer_model_tier("qwen2.5:14b") == "medium"

    def test_small_models(self) -> None:
        assert infer_model_tier("qwen2.5:7b") == "small"
        assert infer_model_tier("llama3.1:8b") == "small"

    def test_unknown_defaults_small(self) -> None:
        assert infer_model_tier("some-unknown-model") == "small"

    def test_ollama_prefix(self) -> None:
        assert infer_model_tier("ollama/qwen2.5:14b") == "medium"

    def test_config_tier_override(self) -> None:
        config = LLMConfig(model="qwen2.5:7b", tier="large")
        assert config.model_tier == "large"

    def test_qwen3_ollama_disables_thinking(self) -> None:
        assert _should_disable_thinking("ollama/qwen3.5:9b") is True


class TestLLMProviderCompatibility:
    @patch("traceweaver.llm.provider.litellm.completion")
    def test_qwen3_ollama_injects_think_false(self, mock_completion) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
        mock_response.usage = None
        mock_completion.return_value = mock_response

        provider = LLMProvider(LLMConfig(model="ollama/qwen3.5:9b"))
        content = provider.complete("system", "user")

        assert content == '{"ok": true}'
        assert mock_completion.call_args.kwargs["extra_body"] == {"think": False}

    @patch("traceweaver.llm.provider.litellm.completion")
    def test_qwen3_ollama_preserves_explicit_think_setting(self, mock_completion) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
        mock_response.usage = None
        mock_completion.return_value = mock_response

        provider = LLMProvider(
            LLMConfig(
                model="ollama/qwen3.5:9b",
                extra_params={"extra_body": {"think": True, "foo": "bar"}},
            )
        )
        provider.complete("system", "user")

        assert mock_completion.call_args.kwargs["extra_body"] == {"think": True, "foo": "bar"}

    @patch("traceweaver.llm.provider.litellm.completion")
    def test_non_qwen3_model_does_not_inject_think_false(self, mock_completion) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"ok": true}'))]
        mock_response.usage = None
        mock_completion.return_value = mock_response

        provider = LLMProvider(LLMConfig(model="ollama/qwen2.5:14b"))
        provider.complete("system", "user")

        assert "extra_body" not in mock_completion.call_args.kwargs


class TestLLMOutputValidation:
    def test_valid_output(self) -> None:
        data = {
            "verdict": "FAIL",
            "failure_point": "AUTHENTICATION",
            "root_cause": "bad key",
            "confidence": "high",
            "evidence": [{"frame_number": 42, "description": "auth failure"}],
            "suggestions": ["check subscriber key"],
            "limitations": [],
            "reasoning": "saw auth failure signal",
        }
        result = parse_llm_diagnosis(data)
        assert result.verdict == "FAIL"
        assert result.confidence == "high"
        assert len(result.evidence) == 1
        assert result.evidence[0].frame_number == 42

    def test_verdict_normalized_to_upper(self) -> None:
        result = parse_llm_diagnosis({"verdict": "fail", "confidence": "high"})
        assert result.verdict == "FAIL"

    def test_confidence_normalized_to_lower(self) -> None:
        result = parse_llm_diagnosis({"verdict": "OK", "confidence": "HIGH"})
        assert result.confidence == "high"

    def test_invalid_verdict_raises(self) -> None:
        with pytest.raises(Exception):
            parse_llm_diagnosis({"verdict": "MAYBE", "confidence": "high"})

    def test_invalid_confidence_raises(self) -> None:
        with pytest.raises(Exception):
            parse_llm_diagnosis({"verdict": "OK", "confidence": "very_high"})

    def test_extra_fields_allowed(self) -> None:
        result = parse_llm_diagnosis({
            "verdict": "OK",
            "confidence": "medium",
            "extra_field": "should not break",
        })
        assert result.verdict == "OK"

    def test_minimal_valid(self) -> None:
        result = parse_llm_diagnosis({"verdict": "INCONCLUSIVE"})
        assert result.verdict == "INCONCLUSIVE"
        assert result.confidence == "medium"


class TestExtractJson:
    def test_plain_json(self) -> None:
        assert _extract_json('{"verdict": "OK"}') == {"verdict": "OK"}

    def test_json_in_code_block(self) -> None:
        text = '```json\n{"verdict": "FAIL"}\n```'
        assert _extract_json(text) == {"verdict": "FAIL"}

    def test_json_with_surrounding_text(self) -> None:
        text = 'Here is my analysis:\n{"verdict": "OK", "confidence": "high"}\nDone.'
        result = _extract_json(text)
        assert result["verdict"] == "OK"

    def test_no_json_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not extract JSON"):
            _extract_json("This is not JSON at all")


class TestPromptBuilding:
    def test_format_timeline_basic(self) -> None:
        session = UESession(
            session_id="test-1",
            ran_ue_ngap_id="1",
            amf_ue_ngap_id="2",
        )
        text = format_timeline(session)
        assert "test-1" in text
        assert "RAN-UE-NGAP-ID: 1" in text

    def test_format_signals_empty(self) -> None:
        text = format_signals([])
        assert "No signals" in text

    def test_format_signals_with_data(self) -> None:
        signals = [
            DiagnosticSignal(
                name="REGISTRATION_REQUEST",
                source="nas_event",
                frame_number=10,
                time_epoch=1.0,
                details={"protocol": "nas_5gmm"},
            ),
        ]
        text = format_signals(signals)
        assert "REGISTRATION_REQUEST" in text
        assert "[10]" in text

    def test_build_prompt_large(self) -> None:
        session = UESession(session_id="s1")
        signals = [DiagnosticSignal(name="REGISTRATION_REQUEST", source="test", frame_number=1)]
        system, user = build_diagnosis_prompt(session, signals, "large")
        assert "5G Core" in system
        assert "REGISTRATION_REQUEST" in user
        assert "JSON" in user

    def test_build_prompt_medium(self) -> None:
        session = UESession(session_id="s1")
        signals = [DiagnosticSignal(name="REGISTRATION_REQUEST", source="test", frame_number=1)]
        system, user = build_diagnosis_prompt(session, signals, "medium")
        assert "step by step" in user.lower() or "Step" in user

    def test_build_prompt_small_includes_hints(self) -> None:
        session = UESession(session_id="s1")
        signals = [
            DiagnosticSignal(name="REGISTRATION_REJECT", source="test", frame_number=1),
            DiagnosticSignal(name="SBI_5XX", source="test", frame_number=2, details={"status": 500}),
        ]
        system, user = build_diagnosis_prompt(session, signals, "small")
        assert "REGISTRATION_REJECT detected" in user
        assert "SBI 5xx" in user


class TestLLMDiagnosisIntegration:
    def test_llm_fallback_on_provider_failure(self) -> None:
        """When LLM provider throws, should fall back to rule engine."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.config = LLMConfig(model="test/model", max_retries=1)
        mock_provider.complete_json.side_effect = Exception("connection refused")

        report = _analyze_capture(FIXTURES / "01_registration_success.pcapng", llm_provider=mock_provider)
        assert report.overall_verdict == "OK"
        assert any("llm_fallback" in n for sess in report.diagnoses for n in sess.notes)

    def test_llm_success_with_mock(self) -> None:
        """When LLM returns valid JSON, should use its verdict."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.config = LLMConfig(model="test/mock-model", max_retries=0)
        mock_provider.complete_json.return_value = {
            "verdict": "OK",
            "failure_point": None,
            "root_cause": None,
            "confidence": "high",
            "evidence": [],
            "suggestions": ["all good"],
            "limitations": [],
            "reasoning": "registration succeeded via NGAP InitialContextSetup",
        }

        report = _analyze_capture(FIXTURES / "01_registration_success.pcapng", llm_provider=mock_provider)
        assert report.overall_verdict == "OK"
        assert any("diagnosed_by: llm" in n for sess in report.diagnoses for n in sess.notes)
        assert mock_provider.complete_json.called

    def test_llm_invalid_verdict_triggers_retry(self) -> None:
        """When LLM returns invalid verdict, retry and eventually fallback."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.config = LLMConfig(model="test/bad", max_retries=1)
        mock_provider.complete_json.return_value = {
            "verdict": "MAYBE_FAIL",
            "confidence": "high",
        }

        report = _analyze_capture(FIXTURES / "01_registration_success.pcapng", llm_provider=mock_provider)
        assert report.overall_verdict == "OK"
        assert any("llm_fallback" in n for sess in report.diagnoses for n in sess.notes)

    def test_rule_engine_when_no_provider(self) -> None:
        """No --model means rule engine, no LLM calls."""
        report = _analyze_capture(FIXTURES / "01_registration_success.pcapng")
        assert report.overall_verdict == "OK"
        assert any("diagnosis_engine: rule" in w for w in report.warnings)
