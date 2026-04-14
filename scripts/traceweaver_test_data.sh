#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT_DIR/.traceweaver"
LOG_DIR="$STATE_DIR/logs"
PCAP_DIR="$ROOT_DIR/tests/fixtures/pcap"
SUBSCRIBER_DIR="$ROOT_DIR/tests/fixtures/subscribers"
CAPTURE_STATE_FILE="$STATE_DIR/capture.env"
GNB_PID_FILE="$STATE_DIR/gnb.pid"
UE_PID_FILE="$STATE_DIR/ue.pid"

REMOTE_HOST="${AILINK5GS_HOST:-192.168.30.193}"
REMOTE_USER="${AILINK5GS_USER:-ailink}"
REMOTE_PASS="${AILINK5GS_PASS:-}"
REMOTE_SUDO_PASS="${AILINK5GS_SUDO_PASS:-$REMOTE_PASS}"
REMOTE_DB="${AILINK5GS_DB:-ailink5gs}"
REMOTE_SUBSCRIBER_COLLECTION="${AILINK5GS_SUBSCRIBER_COLLECTION:-subscribers}"

UERANSIM_HOME="${UERANSIM_HOME:-/home/ailink/UERANSIM}"
GNB_BIN="${GNB_BIN:-$UERANSIM_HOME/build/nr-gnb}"
UE_BIN="${UE_BIN:-$UERANSIM_HOME/build/nr-ue}"
GNB_CFG="${GNB_CFG:-$UERANSIM_HOME/config/custom-gnb.yaml}"
UE_CFG="${UE_CFG:-$UERANSIM_HOME/config/custom-ue.yaml}"

mkdir -p "$STATE_DIR" "$LOG_DIR" "$PCAP_DIR" "$SUBSCRIBER_DIR"

usage() {
    cat <<'EOF'
用法:
  bash scripts/traceweaver_test_data.sh status
  bash scripts/traceweaver_test_data.sh subscriber-show <imsi>
  bash scripts/traceweaver_test_data.sh subscriber-export <imsi> [output.json]
  bash scripts/traceweaver_test_data.sh subscriber-import <input.json>
  bash scripts/traceweaver_test_data.sh capture-start <scenario_name>
  bash scripts/traceweaver_test_data.sh capture-stop [local_output.pcapng]
  bash scripts/traceweaver_test_data.sh gnb-start
  bash scripts/traceweaver_test_data.sh gnb-stop
  bash scripts/traceweaver_test_data.sh ue-start
  bash scripts/traceweaver_test_data.sh ue-stop
  bash scripts/traceweaver_test_data.sh validate <pcap_file>

环境变量:
  AILINK5GS_HOST
  AILINK5GS_USER
  AILINK5GS_PASS
  AILINK5GS_SUDO_PASS
  AILINK5GS_DB
  AILINK5GS_SUBSCRIBER_COLLECTION
  UERANSIM_HOME
  GNB_BIN
  UE_BIN
  GNB_CFG
  UE_CFG
EOF
}

die() {
    echo "$*" >&2
    exit 1
}

require_remote_auth() {
    [[ -n "$REMOTE_PASS" ]] || die "请先设置 AILINK5GS_PASS"
    [[ -n "$REMOTE_SUDO_PASS" ]] || die "请先设置 AILINK5GS_SUDO_PASS"
}

remote_ssh() {
    require_remote_auth
    SSHPASS="$REMOTE_PASS" sshpass -e ssh -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" "$@"
}

remote_scp_from() {
    require_remote_auth
    local remote_path="$1"
    local local_path="$2"
    SSHPASS="$REMOTE_PASS" sshpass -e scp -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}:${remote_path}" "$local_path"
}

remote_scp_to() {
    require_remote_auth
    local local_path="$1"
    local remote_path="$2"
    SSHPASS="$REMOTE_PASS" sshpass -e scp -o StrictHostKeyChecking=no "$local_path" "${REMOTE_USER}@${REMOTE_HOST}:${remote_path}"
}

save_kv() {
    local file="$1"
    shift
    : > "$file"
    while (($#)); do
        local key="$1"
        local value="$2"
        printf '%s=%q\n' "$key" "$value" >> "$file"
        shift 2
    done
}

ensure_binary() {
    local path="$1"
    [[ -x "$path" ]] || die "找不到可执行文件: $path"
}

ensure_file() {
    local path="$1"
    [[ -f "$path" ]] || die "找不到文件: $path"
}

pid_running() {
    local pid_file="$1"
    [[ -f "$pid_file" ]] || return 1
    local pid
    pid="$(cat "$pid_file")"
    [[ -n "$pid" ]] || return 1
    kill -0 "$pid" 2>/dev/null
}

status_cmd() {
    remote_ssh "/opt/ailink5gs/bin/status_all.sh"
}

subscriber_show_cmd() {
    local imsi="${1:?请提供 IMSI}"
    remote_ssh "mongosh --quiet '$REMOTE_DB' --eval 'var d=db.${REMOTE_SUBSCRIBER_COLLECTION}.findOne({imsi:\"${imsi}\"}); print(JSON.stringify(d))'"
}

subscriber_export_cmd() {
    local imsi="${1:?请提供 IMSI}"
    local default_output="$SUBSCRIBER_DIR/${imsi}.json"
    local output="${2:-$default_output}"
    mkdir -p "$(dirname "$output")"
    remote_ssh "mongoexport --quiet --db '$REMOTE_DB' --collection '$REMOTE_SUBSCRIBER_COLLECTION' --query '{\"imsi\":\"${imsi}\"}' --jsonArray" > "$output"
    echo "$output"
}

subscriber_import_cmd() {
    local input="${1:?请提供 JSON 文件路径}"
    ensure_file "$input"
    local remote_tmp="/tmp/traceweaver_subscriber_$(date +%Y%m%d_%H%M%S).json"
    remote_scp_to "$input" "$remote_tmp"
    remote_ssh "mongoimport --quiet --db '$REMOTE_DB' --collection '$REMOTE_SUBSCRIBER_COLLECTION' --mode upsert --upsertFields imsi --file '$remote_tmp' --jsonArray && rm -f '$remote_tmp'"
}

capture_start_cmd() {
    local scenario="${1:?请提供场景名}"
    [[ ! -f "$CAPTURE_STATE_FILE" ]] || die "已有进行中的抓包，请先执行 capture-stop"
    local stamp
    stamp="$(date +%Y%m%d_%H%M%S)"
    local base="${scenario}_${stamp}"
    local remote_dir="/tmp/traceweaver-captures"
    local remote_pcap="${remote_dir}/${base}.pcapng"
    local remote_log="${remote_dir}/${base}.tcpdump.log"
    local remote_pid_file="${remote_dir}/${base}.tcpdump.pid"
    local pid
    pid="$({
        remote_ssh bash -s <<EOF
set -euo pipefail
printf '%s\n' '$REMOTE_SUDO_PASS' | sudo -S -p '' bash -lc 'mkdir -p "$remote_dir"; nohup tcpdump -i any -s 0 -U -w "$remote_pcap" >"$remote_log" 2>&1 </dev/null & echo \$! > "$remote_pid_file"'
sleep 1
cat "$remote_pid_file"
EOF
    })"
    save_kv "$CAPTURE_STATE_FILE" \
        REMOTE_HOST "$REMOTE_HOST" \
        REMOTE_USER "$REMOTE_USER" \
        REMOTE_PCAP "$remote_pcap" \
        REMOTE_LOG "$remote_log" \
        REMOTE_PID_FILE "$remote_pid_file" \
        SCENARIO "$scenario" \
        STARTED_AT "$stamp" \
        TCPDUMP_PID "$pid"
    echo "$remote_pcap"
}

capture_stop_cmd() {
    [[ -f "$CAPTURE_STATE_FILE" ]] || die "没有进行中的抓包"
    source "$CAPTURE_STATE_FILE"
    local output="${1:-$PCAP_DIR/$(basename "$REMOTE_PCAP")}"
    mkdir -p "$(dirname "$output")"
    remote_ssh bash -s <<EOF
set -euo pipefail
printf '%s\n' '$REMOTE_SUDO_PASS' | sudo -S -p '' bash -lc '
if [ -f "$REMOTE_PID_FILE" ]; then
    pid="\$(cat "$REMOTE_PID_FILE")"
    if [ -n "\$pid" ]; then
        kill "\$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$REMOTE_PID_FILE"
fi
if [ -f "$REMOTE_PCAP" ]; then
    chmod 644 "$REMOTE_PCAP" || true
fi
if [ -f "$REMOTE_LOG" ]; then
    chmod 644 "$REMOTE_LOG" || true
fi
'
sleep 1
EOF
    remote_scp_from "$REMOTE_PCAP" "$output"
    rm -f "$CAPTURE_STATE_FILE"
    echo "$output"
}

gnb_start_cmd() {
    ensure_binary "$GNB_BIN"
    ensure_file "$GNB_CFG"
    pid_running "$GNB_PID_FILE" && die "gNB 已在运行"
    nohup "$GNB_BIN" -c "$GNB_CFG" > "$LOG_DIR/gnb.log" 2>&1 &
    echo $! > "$GNB_PID_FILE"
    echo "$LOG_DIR/gnb.log"
}

gnb_stop_cmd() {
    pid_running "$GNB_PID_FILE" || die "gNB 未运行"
    kill "$(cat "$GNB_PID_FILE")"
    rm -f "$GNB_PID_FILE"
}

ue_start_cmd() {
    ensure_binary "$UE_BIN"
    ensure_file "$UE_CFG"
    pid_running "$UE_PID_FILE" && die "UE 已在运行"
    nohup "$UE_BIN" -c "$UE_CFG" > "$LOG_DIR/ue.log" 2>&1 &
    echo $! > "$UE_PID_FILE"
    echo "$LOG_DIR/ue.log"
}

ue_stop_cmd() {
    pid_running "$UE_PID_FILE" || die "UE 未运行"
    kill "$(cat "$UE_PID_FILE")"
    rm -f "$UE_PID_FILE"
}

validate_cmd() {
    local file="${1:?请提供 pcap 文件}"
    ensure_file "$file"
    echo "== protocols =="
    tshark -r "$file" -Y "ngap" -c 1 >/dev/null 2>&1 && echo "ngap: yes" || echo "ngap: no"
    tshark -r "$file" -Y "nas-5gs" -c 1 >/dev/null 2>&1 && echo "nas-5gs: yes" || echo "nas-5gs: no"
    tshark -r "$file" -Y "http2" -c 1 >/dev/null 2>&1 && echo "http2: yes" || echo "http2: no"
    tshark -r "$file" -Y "pfcp" -c 1 >/dev/null 2>&1 && echo "pfcp: yes" || echo "pfcp: no"
    echo "== nas mm types =="
    tshark -r "$file" -Y "nas-5gs" -T fields -e nas_5gs.mm.message_type -e nas_5gs.sm.message_type | sort | uniq -c || true
    echo "== ngap procedure codes =="
    tshark -r "$file" -Y "ngap" -T fields -e ngap.procedureCode | sort | uniq -c || true
    echo "== sbi paths =="
    tshark -r "$file" -Y "http2.headers.path" -T fields -e http2.headers.path | sort | uniq -c || true
    echo "== pfcp message types =="
    tshark -r "$file" -Y "pfcp" -T fields -e pfcp.msg_type | sort | uniq -c || true
}

cmd="${1:-}"
case "$cmd" in
    status)
        status_cmd
        ;;
    subscriber-show)
        shift
        subscriber_show_cmd "$@"
        ;;
    subscriber-export)
        shift
        subscriber_export_cmd "$@"
        ;;
    subscriber-import)
        shift
        subscriber_import_cmd "$@"
        ;;
    capture-start)
        shift
        capture_start_cmd "$@"
        ;;
    capture-stop)
        shift
        capture_stop_cmd "$@"
        ;;
    gnb-start)
        gnb_start_cmd
        ;;
    gnb-stop)
        gnb_stop_cmd
        ;;
    ue-start)
        ue_start_cmd
        ;;
    ue-stop)
        ue_stop_cmd
        ;;
    validate)
        shift
        validate_cmd "$@"
        ;;
    *)
        usage
        exit 1
        ;;
esac
