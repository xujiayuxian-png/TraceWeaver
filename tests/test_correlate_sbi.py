from traceweaver.profiles.open5gs_5gc.assemble.sbi import correlate_sbi_to_sessions, pair_sbi_calls
from traceweaver.profiles.open5gs_5gc.domain.records import ExtractedRecordSet, NormalizedRecord
from traceweaver.profiles.open5gs_5gc.domain.sessions import UESession


def _build_http2_record_set() -> ExtractedRecordSet:
    return ExtractedRecordSet(
        path="synthetic.pcapng",
        file_name="synthetic.pcapng",
        display_filter="http2",
        decode_as=[],
        tshark_version="test",
        resolved_fields={},
        unresolved_fields=[],
        warnings=[],
        record_count=2,
        records=[
            NormalizedRecord(
                frame_number=1,
                time_epoch=1.0,
                protocols=["eth", "ip", "tcp", "http2"],
                primary_protocol="http2",
                src_ip="10.0.0.1",
                dst_ip="10.0.0.2",
                src_port=1234,
                dst_port=7777,
                transport_protocol="tcp",
                fields={
                    "tcp.stream": "7",
                    "http2.streamid": "1",
                    "http2.headers.method": "POST",
                    "http2.headers.path": "/nausf-auth/v1/ue-authentications",
                },
            ),
            NormalizedRecord(
                frame_number=2,
                time_epoch=1.1,
                protocols=["eth", "ip", "tcp", "http2"],
                primary_protocol="http2",
                src_ip="10.0.0.2",
                dst_ip="10.0.0.1",
                src_port=7777,
                dst_port=1234,
                transport_protocol="tcp",
                fields={
                    "tcp.stream": "7",
                    "http2.streamid": "1",
                    "http2.headers.status": "201",
                },
            ),
        ],
    )


def test_pair_sbi_calls_parses_numeric_fields() -> None:
    calls = pair_sbi_calls(_build_http2_record_set())

    assert len(calls) == 1
    call = calls[0]
    assert call.tcp_stream == 7
    assert call.stream_id == 1
    assert call.status == 201


def test_correlate_sbi_to_sessions_emits_summary_warning() -> None:
    calls = pair_sbi_calls(_build_http2_record_set())
    warnings: list[str] = []

    correlate_sbi_to_sessions(calls, [UESession(session_id="ue-1")], warnings=warnings)

    assert any(item.startswith("sbi_correlation_summary:") for item in warnings)
