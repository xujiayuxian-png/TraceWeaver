#!/usr/bin/env bash
# Bash twin of capture_all.ps1. See that file for full docs.

set -euo pipefail

NETSHOOT_IMAGE="${NETSHOOT_IMAGE:-nicolaka/netshoot}"

FIXTURE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${FIXTURE_ROOT}"
PCAP_DIR="${FIXTURE_ROOT}/pcaps"
mkdir -p "${PCAP_DIR}"

COMPOSE_NAME="web_l4l7"
CLIENT_NAME="web_l4l7_client"
CAP_NAME="web_l4l7_cap"

stop_capture() { docker rm -f "${CAP_NAME}" >/dev/null 2>&1 || true; }
stop_client()  { docker rm -f "${CLIENT_NAME}" >/dev/null 2>&1 || true; }
cleanup_all() {
    stop_capture
    stop_client
    docker compose -p "${COMPOSE_NAME}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup_all ERR EXIT

docker version --format '{{.Server.Version}}' >/dev/null

echo "[1/3] docker compose up -d (build on first run)..."
if ! docker compose -p "${COMPOSE_NAME}" up -d --build; then
    cat >&2 <<'EOF'
docker compose up failed. Most common causes:
  (a) Image pull blocked by a dead HTTP proxy
      -> Check Docker Desktop > Settings > Resources > Proxies
  (b) Firewall blocks registry-1.docker.io
      -> Configure a mirror in Docker Engine settings
EOF
    exit 1
fi
sleep 3

echo "[2/3] launching client container..."
stop_client
docker run -d \
    --name "${CLIENT_NAME}" \
    --network "${COMPOSE_NAME}_web_l4l7_net" \
    --ip 10.5.0.100 \
    --dns 10.5.0.10 \
    --cap-add NET_ADMIN \
    --cap-add NET_RAW \
    -v "${COMPOSE_NAME}_certs:/shared:ro" \
    "${NETSHOOT_IMAGE}" \
    sleep infinity >/dev/null

# Wait for the CA cert (nginx publishes it on startup, ~1s).
for i in $(seq 1 20); do
    if docker exec "${CLIENT_NAME}" test -f /shared/ca.crt 2>/dev/null; then
        break
    fi
    sleep 0.25
done

capture_scenario() {
    local name="$1"; shift
    local settle_ms="${SETTLE_MS:-800}"
    local pcap="/tmp/${name}.pcapng"
    echo ">> ${name}"

    stop_capture
    # tshark drops privileges via dumpcap and cannot write directly to
    # volume-mounted directories on some setups. Write to /tmp inside the
    # container, then copy out after capture completes.
    docker run -d \
        --name "${CAP_NAME}" \
        --network "container:${CLIENT_NAME}" \
        --cap-add NET_ADMIN \
        --cap-add NET_RAW \
        -v "${PCAP_DIR}:/pcaps" \
        "${NETSHOOT_IMAGE}" \
        sh -c "tshark -i eth0 -w '${pcap}' -F pcapng -q >/dev/null 2>&1 &
               TSHARK_PID=\$!; sleep 9999 & WAIT_PID=\$!; wait \$WAIT_PID" >/dev/null

    sleep "$(awk "BEGIN {print ${settle_ms}/1000}")"
    "$@" || true
    sleep "$(awk "BEGIN {print ${settle_ms}/1000}")"

    # Graceful stop: send SIGINT to tshark so it flushes the pcap footer.
    docker stop -t 5 "${CAP_NAME}" >/dev/null 2>&1 || true
    docker cp "${CAP_NAME}:${pcap}" "${PCAP_DIR}/${name}.pcapng" 2>/dev/null || true
    docker rm -f "${CAP_NAME}" >/dev/null 2>&1 || true
}

echo "[3/3] running 5 capture scenarios..."

capture_scenario "01_web_ok" \
    docker exec "${CLIENT_NAME}" curl -sS -o /dev/null --max-time 5 \
        --cacert /shared/ca.crt https://server.local/

capture_scenario "02_dns_nxdomain" \
    docker exec "${CLIENT_NAME}" sh -c "curl -sS -o /dev/null --max-time 5 https://does-not-exist.local/ ; true"

capture_scenario "03_tcp_rst" \
    docker exec "${CLIENT_NAME}" sh -c "curl -sS -o /dev/null --max-time 3 http://server.local:9999/ ; true"

capture_scenario "04_tls_cert_expired" \
    docker exec "${CLIENT_NAME}" sh -c "curl -sS -o /dev/null --max-time 5 --cacert /shared/ca.crt https://tls-broken.local:4443/ ; true"

# curl 8.18+ supports ws:// natively and keeps the connection open for
# receive. timeout 5s allows server-side RST to fire (3s) before client
# gives up. Falls back to websocat if curl lacks WebSocket support.
SETTLE_MS=1500 capture_scenario "05_ws_idle_killed" \
    docker exec "${CLIENT_NAME}" sh -c 'timeout 5 curl -v ws://ws-flaky.local:8080/ 2>&1 || true'

trap - ERR EXIT
cleanup_all

echo
echo "Done. PCAPs are in: ${PCAP_DIR}"
ls -lh "${PCAP_DIR}"/*.pcapng
