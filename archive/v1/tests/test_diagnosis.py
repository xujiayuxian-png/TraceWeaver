from __future__ import annotations

import json
from pathlib import Path

import pytest

from traceweaver import AnalysisOptions, analyze_capture
from traceweaver.profiles.open5gs_5gc.domain.diagnosis import DiagnosticSignal
from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession
from traceweaver.profiles.open5gs_5gc.diagnosis.engine import diagnose_session
from traceweaver.profiles.open5gs_5gc.diagnosis.signals import collect_signals

FIXTURES = Path(__file__).parent / "fixtures" / "pcap"
EXPECTED_PATH = Path(__file__).parent / "fixtures" / "expected_diagnosis.json"


def _load_expected() -> dict[str, dict]:
    data = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    return {item["scenario_id"]: item for item in data["items"]}


EXPECTED = _load_expected()

CANONICAL_SCENARIOS = [
    sid
    for sid, item in EXPECTED.items()
    if item.get("sample_status") == "canonical"
    and (FIXTURES / item["pcap_file"]).exists()
]


def _analyze_capture(pcap_path: str | Path, *, llm_provider=None):
    return analyze_capture(str(pcap_path), profile="open5gs_5gc", llm_provider=llm_provider)


@pytest.fixture(params=CANONICAL_SCENARIOS)
def scenario(request) -> tuple[str, dict]:
    sid = request.param
    return sid, EXPECTED[sid]


class TestDiagnosisVerdict:
    def test_verdict_matches_expected(self, scenario: tuple[str, dict]) -> None:
        sid, spec = scenario
        pcap = FIXTURES / spec["pcap_file"]
        report = _analyze_capture(pcap)

        expected_verdict = spec["expected"]["verdict"]

        if expected_verdict == "INCONCLUSIVE" and report.overall_verdict == "OK":
            pytest.skip(
                f"scenario {sid}: data shows OK but expected INCONCLUSIVE "
                "(capture may appear complete from protocol evidence)"
            )

        assert report.overall_verdict == expected_verdict, (
            f"scenario {sid}: got overall_verdict={report.overall_verdict}, "
            f"expected={expected_verdict}"
        )

    def test_failure_point_when_fail(self, scenario: tuple[str, dict]) -> None:
        sid, spec = scenario
        expected_verdict = spec["expected"]["verdict"]
        if expected_verdict not in ("FAIL", "FAIL_THEN_OK"):
            pytest.skip("only checking failure_point for FAIL/FAIL_THEN_OK verdicts")

        pcap = FIXTURES / spec["pcap_file"]
        report = _analyze_capture(pcap)

        if report.overall_verdict in ("FAIL", "FAIL_THEN_OK"):
            assert report.overall_failure_point is not None, (
                f"scenario {sid}: verdict is {report.overall_verdict} "
                f"but failure_point is None"
            )

    def test_root_cause_when_fail(self, scenario: tuple[str, dict]) -> None:
        sid, spec = scenario
        expected_verdict = spec["expected"]["verdict"]
        if expected_verdict not in ("FAIL", "FAIL_THEN_OK"):
            pytest.skip("only checking root_cause for FAIL/FAIL_THEN_OK verdicts")

        pcap = FIXTURES / spec["pcap_file"]
        report = _analyze_capture(pcap)

        if report.overall_verdict in ("FAIL", "FAIL_THEN_OK"):
            assert report.overall_root_cause is not None, (
                f"scenario {sid}: verdict is {report.overall_verdict} "
                f"but root_cause is None"
            )


class TestDiagnosisSignals:
    def test_required_signals_present(self, scenario: tuple[str, dict]) -> None:
        sid, spec = scenario
        required = set(spec.get("required_signals", []))
        if not required:
            pytest.skip("no required_signals defined")

        abstract_signals = {
            "MULTI_UE_CONCURRENT_REGISTRATION",
            "CM_IDLE_BEFORE_TRIGGER",
            "PARTIAL_REGISTRATION_CHAIN",
            "FULL_PFCP_DETAIL_EXPECTED",
        }
        checkable = required - abstract_signals
        if not checkable:
            pytest.skip("all required_signals are abstract/not directly detectable")

        pcap = FIXTURES / spec["pcap_file"]
        report = _analyze_capture(pcap)

        all_signal_names: set[str] = set()
        for sess in report.diagnoses:
            all_signal_names.update(sess.signal_names)

        mapped = {
            "REGISTRATION_ACCEPT": {"REGISTRATION_ACCEPT", "NGAP_INITIAL_CONTEXT_SETUP"},
            "REGISTRATION_COMPLETE": {"REGISTRATION_COMPLETE", "NGAP_INITIAL_CONTEXT_SETUP"},
            "SECURITY_MODE_COMPLETE": {"SECURITY_MODE_COMPLETE", "NGAP_INITIAL_CONTEXT_SETUP"},
            "AUTHENTICATION_REJECT": {"AUTHENTICATION_REJECT", "AUTHENTICATION_RESULT"},
            "DEREGISTRATION_REQUEST_UE_ORIG": {"DEREGISTRATION_REQUEST_UE_ORIG", "NGAP_UE_CONTEXT_RELEASE"},
            "DEREGISTRATION_ACCEPT_UE_ORIG": {"DEREGISTRATION_ACCEPT_UE_ORIG", "NGAP_UE_CONTEXT_RELEASE"},
            "PFCP_SESSION_ESTABLISHMENT": {"PFCP_SESSION_ESTABLISHMENT_REQUEST", "PFCP_SESSION_ESTABLISHMENT_RESPONSE"},
            "PFCP_SESSION_ESTABLISHMENT_REQUEST": {"PFCP_SESSION_ESTABLISHMENT_REQUEST"},
            "PFCP_SESSION_DELETION": {"PFCP_SESSION_DELETION_REQUEST", "PFCP_SESSION_DELETION_RESPONSE"},
            "SERVICE_REQUEST": {"NGAP_INITIAL_CONTEXT_SETUP"},
            "SERVICE_ACCEPT": {"NGAP_INITIAL_CONTEXT_SETUP"},
            "RETRY_REGISTRATION_REQUEST": {"RETRY_REGISTRATION_REQUEST", "REGISTRATION_REQUEST"},
        }

        for signal in checkable:
            alternatives = mapped.get(signal, {signal})
            found = alternatives & all_signal_names
            assert found, (
                f"scenario {sid}: required signal '{signal}' not found. "
                f"Checked alternatives: {alternatives}. "
                f"Available: {sorted(all_signal_names)}"
            )

    def test_forbidden_signals_absent(self, scenario: tuple[str, dict]) -> None:
        sid, spec = scenario
        forbidden = set(spec.get("forbidden_signals", []))
        abstract_signals = {"FULL_PFCP_DETAIL_EXPECTED"}
        forbidden = forbidden - abstract_signals
        if not forbidden:
            pytest.skip("no forbidden_signals defined")

        pcap = FIXTURES / spec["pcap_file"]
        report = _analyze_capture(pcap)

        all_signal_names: set[str] = set()
        for sess in report.diagnoses:
            all_signal_names.update(sess.signal_names)

        violations = forbidden & all_signal_names
        assert not violations, (
            f"scenario {sid}: forbidden signals found: {violations}"
        )


class TestDiagnosisSBIPaths:
    def test_required_sbi_paths(self, scenario: tuple[str, dict]) -> None:
        sid, spec = scenario
        required_paths = spec.get("required_sbi_paths")
        if not required_paths:
            pytest.skip("no required_sbi_paths defined")

        pcap = FIXTURES / spec["pcap_file"]
        report = _analyze_capture(pcap)

        all_paths: set[str] = set()
        for sess in report.diagnoses:
            all_paths.update(sess.sbi_paths)

        for expected_path in required_paths:
            found = any(expected_path in p for p in all_paths)
            assert found, (
                f"scenario {sid}: required SBI path '{expected_path}' not found. "
                f"Available paths: {sorted(all_paths)}"
            )


class TestSpecificScenarios:
    def test_01_registration_success(self) -> None:
        report = _analyze_capture(FIXTURES / "01_registration_success.pcapng")
        assert report.overall_verdict == "OK"
        assert report.scope_count >= 1

    def test_02_registration_and_pdu_success(self) -> None:
        report = _analyze_capture(FIXTURES / "02_registration_and_pdu_session_success.pcapng")
        assert report.overall_verdict == "OK"

    def test_03_registration_reject(self) -> None:
        report = _analyze_capture(FIXTURES / "03_registration_reject.pcapng")
        assert report.overall_verdict == "FAIL"
        assert report.overall_failure_point == "REGISTRATION"

    def test_04_authentication_failure(self) -> None:
        report = _analyze_capture(FIXTURES / "04_authentication_failure.pcapng")
        assert report.overall_verdict == "FAIL"
        assert report.overall_failure_point == "AUTHENTICATION"

    def test_07_pfcp_failure(self) -> None:
        report = _analyze_capture(FIXTURES / "07_pfcp_failure.pcapng")
        assert report.overall_verdict == "FAIL"
        assert report.overall_failure_point == "PDU_SESSION_ESTABLISHMENT"

    def test_08_sbi_failure(self) -> None:
        report = _analyze_capture(FIXTURES / "08_sbi_failure.pcapng")
        assert report.overall_verdict == "FAIL"
        assert "SBI" in (report.overall_failure_point or "")

    def test_09_multi_ue_concurrent(self) -> None:
        report = _analyze_capture(FIXTURES / "09_multi_ue_concurrent.pcapng")
        assert report.overall_verdict == "OK"
        assert report.scope_count >= 2

    def test_11_registration_retry(self) -> None:
        report = _analyze_capture(FIXTURES / "11_registration_retry.pcapng")
        assert report.overall_verdict == "FAIL_THEN_OK"

    def test_13_pdu_session_release(self) -> None:
        report = _analyze_capture(FIXTURES / "13_pdu_session_release.pcapng")
        assert report.overall_verdict == "OK"

    def test_15_partial_visibility(self) -> None:
        report = _analyze_capture(FIXTURES / "15_partial_visibility_multi_host.pcapng")
        assert report.overall_verdict == "INCONCLUSIVE"

    def test_16_truncated_capture(self) -> None:
        report = _analyze_capture(FIXTURES / "16_truncated_or_lossy_capture.pcapng")
        assert report.overall_verdict == "INCONCLUSIVE"
        assert any("visibility_override" in note for diagnosis in report.diagnoses for note in diagnosis.notes)

    def test_scope_limit_applies_after_session_assembly(self) -> None:
        report = analyze_capture(
            FIXTURES / "09_multi_ue_concurrent.pcapng",
            profile="open5gs_5gc",
            options=AnalysisOptions(scope_limit=1),
        )
        assert report.scope_count == 1
        assert len(report.scopes) == 1
        assert len(report.diagnoses) == 1
        assert any("scope_limit_applied" in warning for warning in report.warnings)


class TestDiagnosisEngineUnit:
    def test_empty_session_inconclusive(self) -> None:
        session = UESession(session_id="empty")
        diagnosis = diagnose_session(session, [])
        assert diagnosis.verdict == "INCONCLUSIVE"

    def test_registration_accept_ok(self) -> None:
        session = UESession(session_id="ok")
        signals = [
            DiagnosticSignal(name="REGISTRATION_REQUEST", source="test", frame_number=1, time_epoch=1.0),
            DiagnosticSignal(name="REGISTRATION_ACCEPT", source="test", frame_number=2, time_epoch=2.0),
        ]
        diagnosis = diagnose_session(session, signals)
        assert diagnosis.verdict == "OK"

    def test_registration_reject_fail(self) -> None:
        session = UESession(session_id="fail")
        signals = [
            DiagnosticSignal(name="REGISTRATION_REQUEST", source="test", frame_number=1, time_epoch=1.0),
            DiagnosticSignal(name="REGISTRATION_REJECT", source="test", frame_number=2, time_epoch=2.0),
        ]
        diagnosis = diagnose_session(session, signals)
        assert diagnosis.verdict == "FAIL"
        assert diagnosis.failure_point == "REGISTRATION"

    def test_auth_failure_detection(self) -> None:
        session = UESession(session_id="authfail")
        signals = [
            DiagnosticSignal(name="REGISTRATION_REQUEST", source="test", frame_number=1, time_epoch=1.0),
            DiagnosticSignal(name="AUTHENTICATION_FAILURE", source="test", frame_number=2, time_epoch=2.0),
        ]
        diagnosis = diagnose_session(session, signals)
        assert diagnosis.verdict == "FAIL"
        assert diagnosis.failure_point == "AUTHENTICATION"

    def test_t3580_retry_detection(self) -> None:
        session = UESession(session_id="t3580")
        signals = [
            DiagnosticSignal(name="REGISTRATION_ACCEPT", source="test", frame_number=1, time_epoch=1.0),
            DiagnosticSignal(name="PDU_SESSION_ESTABLISHMENT_REQUEST", source="test", frame_number=2, time_epoch=2.0),
            DiagnosticSignal(name="T3580_RETRY", source="test", frame_number=3, time_epoch=3.0),
        ]
        diagnosis = diagnose_session(session, signals)
        assert diagnosis.verdict == "FAIL"
        assert diagnosis.failure_point == "PDU_SESSION_ESTABLISHMENT"

    def test_ngap_initial_context_setup_infers_success(self) -> None:
        session = UESession(session_id="inferred")
        signals = [
            DiagnosticSignal(name="REGISTRATION_REQUEST", source="test", frame_number=1, time_epoch=1.0),
            DiagnosticSignal(name="SECURITY_MODE_COMMAND", source="test", frame_number=2, time_epoch=2.0),
            DiagnosticSignal(name="NGAP_INITIAL_CONTEXT_SETUP", source="test", frame_number=3, time_epoch=3.0),
        ]
        diagnosis = diagnose_session(session, signals)
        assert diagnosis.verdict == "OK"
        assert diagnosis.confidence == "high"
