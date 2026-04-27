"""
测试 tshark 是否能从 NGAP InitialContextSetupRequest 里提取嵌套的 NAS 消息。

问题：REGISTRATION_ACCEPT (message_type=0x42) 封装在 NGAP 的 NAS PDU 里，
tshark 默认 fields extractor 可能无法访问嵌套层。
"""

import subprocess
import shutil
from pathlib import Path

PCAP_FILE = Path("tests/fixtures/pcap/01_registration_success.pcapng")
TSHARK = shutil.which("tshark") or r"C:\Program Files\Wireshark\tshark.exe"


def run_tshark(args: list[str]) -> str:
    """Run tshark and return stdout."""
    cmd = [TSHARK] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print(f"tshark stderr: {result.stderr[:500]}")
    return result.stdout


def test_basic_extraction():
    """测试基本的 NAS 消息类型提取（顶层 NAS）。"""
    print("=" * 60)
    print("TEST 1: 顶层 NAS 消息 (Registration Request)")
    print("=" * 60)

    # 帧 141 是 InitialUEMessage 里的 Registration Request
    stdout = run_tshark([
        "-r", str(PCAP_FILE),
        "-n",
        "-Y", "frame.number == 141",
        "-T", "fields",
        "-e", "frame.number",
        "-e", "frame.protocols",
        "-e", "nas-5gs.mm.message_type",
        "-e", "ngap.procedureCode",
    ])
    print("Result:")
    print(stdout or "(empty)")
    print()


def test_initial_context_setup():
    """测试 InitialContextSetupRequest 里的 NAS。"""
    print("=" * 60)
    print("TEST 2: InitialContextSetupRequest 帧 (467)")
    print("=" * 60)

    stdout = run_tshark([
        "-r", str(PCAP_FILE),
        "-n",
        "-Y", "frame.number == 467",
        "-T", "fields",
        "-e", "frame.number",
        "-e", "frame.protocols",
        "-e", "ngap.procedureCode",
        "-e", "nas-5gs.mm.message_type",  # 这个是空的
        "-e", "ngap.nas_pdu",  # 尝试取 NAS PDU 原始数据
    ])
    print("Fields extraction result:")
    print(stdout or "(empty)")

    # 用 -V 看详细信息
    print("\n--- Full decode (-V) ---")
    stdout_v = run_tshark([
        "-r", str(PCAP_FILE),
        "-n",
        "-Y", "frame.number == 467",
        "-V",
    ])
    # 只显示 NAS 相关行
    nas_lines = [line for line in stdout_v.splitlines() if "nas-5gs" in line.lower() or "registration" in line.lower()]
    print("\n".join(nas_lines[:30]) if nas_lines else "(no NAS lines found)")
    print()


def test_all_nas_frames():
    """列出所有能提取到 NAS message_type 的帧。"""
    print("=" * 60)
    print("TEST 3: 所有能解出 nas-5gs.mm.message_type 的帧")
    print("=" * 60)

    stdout = run_tshark([
        "-r", str(PCAP_FILE),
        "-n",
        "-Y", "nas-5gs.mm.message_type",
        "-T", "fields",
        "-e", "frame.number",
        "-e", "nas-5gs.mm.message_type",
        "-e", "ngap.procedureCode",
        "-e", "frame.protocols",
    ])
    print("Result (frame, mm_type, ngap_proc, protocols):")
    print(stdout or "(empty)")

    # 解析看看有哪些 NAS 类型
    print("\n--- NAS MM Message Types Found ---")
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            frame_num = parts[0]
            mm_type = parts[1]
            mm_val = int(mm_type, 0) if mm_type else 0
            print(f"  Frame {frame_num}: mm_type={mm_type} (0x{mm_val:02x})")
    print()


def test_ngap_with_nas_pdu():
    """测试专门提取 NGAP 里携带 NAS PDU 的情况。"""
    print("=" * 60)
    print("TEST 4: NGAP 消息里的 NAS PDU 字段")
    print("=" * 60)

    # 看所有 NGAP 消息，检查哪些有 nas_pdu
    stdout = run_tshark([
        "-r", str(PCAP_FILE),
        "-n",
        "-Y", "ngap",
        "-T", "fields",
        "-e", "frame.number",
        "-e", "ngap.procedureCode",
        "-e", "ngap.nas_pdu",
        "-e", "nas-5gs.mm.message_type",
    ])
    print("Result (frame, ngap_proc, nas_pdu_present, mm_type):")
    lines = stdout.strip().split("\n")
    for line in lines[:20]:  # 只显示前20行
        parts = line.split("\t")
        if len(parts) >= 3:
            nas_pdu_present = "YES" if parts[2] else "NO"
            mm_type = parts[3] if len(parts) > 3 else "N/A"
            print(f"  Frame {parts[0]}: ngap={parts[1]}, nas_pdu={nas_pdu_present}, mm_type={mm_type}")
    if len(lines) > 20:
        print(f"  ... ({len(lines) - 20} more lines)")
    print()


def main():
    print(f"Testing with tshark: {TSHARK}")
    print(f"PCAP file: {PCAP_FILE}")
    print()

    if not PCAP_FILE.exists():
        print(f"ERROR: PCAP file not found: {PCAP_FILE}")
        return 1

    test_basic_extraction()
    test_initial_context_setup()
    test_all_nas_frames()
    test_ngap_with_nas_pdu()

    print("=" * 60)
    print("CONCLUSION")
    print("=" * 60)
    print("如果 TEST 3 里没有 frame 467 的 mm_type=0x42 (REGISTRATION_ACCEPT),")
    print("说明 tshark 无法直接从 InitialContextSetupRequest 提取嵌套 NAS 类型。")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
