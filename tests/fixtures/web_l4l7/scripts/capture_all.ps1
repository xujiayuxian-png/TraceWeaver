<#
.SYNOPSIS
    Build the docker test bench, capture 5 pcaps covering DNS / TCP /
    TLS / WebSocket failure modes, then tear down.

.DESCRIPTION
    Output: tests/fixtures/web_l4l7/pcaps/01..05_*.pcapng

    Run from anywhere; the script normalizes its working directory to
    the fixture root.

    Total runtime ~2-3 minutes (docker build dominates first run; pcap
    captures themselves are seconds each).

.NOTES
    Requires: Docker Desktop running. No admin/root needed.
#>

[CmdletBinding()]
param(
    # Default to latest because tag pinning across netshoot releases is
    # historically unstable; override with -NetshootImage if you need
    # a frozen version.
    [string]$NetshootImage = "nicolaka/netshoot"
)

$ErrorActionPreference = "Stop"
# PS 7.3+ honours this; PS 5.1 ignores it. Either way: native command
# stderr does not auto-fail the script, so we use try/catch + explicit
# `2>$null` guards on the cleanup paths.
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $PSNativeCommandUseErrorActionPreference = $true
}

# --- Always run from the fixture root, regardless of caller's cwd. ---
$FixtureRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $FixtureRoot
$PcapDir = Join-Path $FixtureRoot "pcaps"
if (-not (Test-Path $PcapDir)) { New-Item -ItemType Directory -Path $PcapDir | Out-Null }

$ComposeName = "web_l4l7"
$ClientName  = "web_l4l7_client"
$CapName     = "web_l4l7_cap"

function Remove-ContainerIfExists {
    param([Parameter(Mandatory=$true)][string]$Name)
    # `docker rm -f` writes to stderr when the container is missing,
    # and $ErrorActionPreference=Stop would turn that stderr line into
    # a terminating NativeCommandError. Filter by `ps -aq` first.
    $id = & docker ps -aq --filter "name=^${Name}$" 2>&1
    if ($LASTEXITCODE -eq 0 -and $id) {
        & docker rm -f $Name *>&1 | Out-Null
    }
}

function Stop-Capture { Remove-ContainerIfExists $CapName }
function Stop-Client  { Remove-ContainerIfExists $ClientName }

function Cleanup-All {
    Stop-Capture
    Stop-Client
    # Wrap in cmd.exe so docker's stderr ("No resource found to remove",
    # written when the project is already empty) stays inside the cmd
    # process and doesn't get promoted to a NativeCommandError by
    # PowerShell 5.1's `$ErrorActionPreference = Stop`.
    # `-v` so the certs volume is freshly minted next run; otherwise an
    # old ca.crt from a previous invocation could race against the new
    # ca.key the nginx entrypoint just generated.
    & cmd.exe /c "docker compose -p $ComposeName down -v --remove-orphans 2>&1" | Out-Null
}

# --- Pre-flight: docker reachable AND able to pull images? ---
try {
    & docker version --format '{{.Server.Version}}' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker daemon not reachable" }
}
catch {
    Write-Error "Docker is not running. Start Docker Desktop and retry."
}

trap { Cleanup-All; break }

# --- 1. Bring up the test bench. ---
Write-Host "[1/3] docker compose up -d (build on first run, ~1-2 min)..." -ForegroundColor Cyan
& docker compose -p $ComposeName up -d --build
if ($LASTEXITCODE -ne 0) {
    Cleanup-All
    Write-Error @"
docker compose up failed. Most common causes on Windows:
  (a) Image pull blocked by a dead HTTP proxy in Docker Desktop settings
      -> Settings > Resources > Proxies : either start the proxy or
         switch to 'System proxy' / 'No proxy'.
  (b) Corporate firewall blocks registry-1.docker.io
      -> Add a mirror in Settings > Docker Engine:
         { "registry-mirrors": ["https://<your-id>.mirror.aliyuncs.com"] }
  (c) Docker Desktop just started and daemon not fully up
      -> Wait 30s and rerun.
"@
    exit 1
}
# Give services a moment to settle (cert generation, websocket bind).
Start-Sleep -Seconds 3

# --- 2. Start the long-running client container. ---
# Pinned IP for client: 10.5.0.100. DNS forced to dnsmasq (10.5.0.10).
# Mounts the certs volume so curl can `--cacert /shared/ca.crt`.
Write-Host "[2/3] launching client container..." -ForegroundColor Cyan
Stop-Client
docker run -d `
    --name $ClientName `
    --network "${ComposeName}_web_l4l7_net" `
    --ip 10.5.0.100 `
    --dns 10.5.0.10 `
    --cap-add NET_ADMIN `
    --cap-add NET_RAW `
    -v "${ComposeName}_certs:/shared:ro" `
    $NetshootImage `
    sleep infinity | Out-Null

# Wait for the CA cert to actually appear in the shared volume
# (nginx's gen_certs.py runs at container start; takes ~1s).
$caReady = $false
for ($i = 0; $i -lt 20; $i++) {
    & docker exec $ClientName test -f /shared/ca.crt 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $caReady = $true; break }
    Start-Sleep -Milliseconds 250
}
if (-not $caReady) {
    Cleanup-All
    Write-Error "Timed out waiting for /shared/ca.crt; nginx entrypoint likely failed."
}

# --- helper: take one capture window. ---
function Capture-Scenario {
    param(
        [Parameter(Mandatory=$true)] [string]$Name,
        [Parameter(Mandatory=$true)] [scriptblock]$Action,
        [int]$SettleMillis = 800
    )

    $pcap = "/pcaps/$Name.pcapng"
    Write-Host ">> $Name" -ForegroundColor Yellow

    Stop-Capture
    docker run -d `
        --name $CapName `
        --network "container:$ClientName" `
        --cap-add NET_ADMIN `
        --cap-add NET_RAW `
        -v "${PcapDir}:/pcaps" `
        $NetshootImage `
        tshark -i eth0 -w $pcap -F pcapng -q | Out-Null

    Start-Sleep -Milliseconds $SettleMillis
    & $Action
    Start-Sleep -Milliseconds $SettleMillis

    Stop-Capture
}

Write-Host "[3/3] running 5 capture scenarios..." -ForegroundColor Cyan

# --- Scenario 1: clean web request (DNS + TCP + TLS all healthy). ---
# Uses --cacert (not -k) so the pcap shows a real successful TLS handshake.
Capture-Scenario -Name "01_web_ok" -Action {
    docker exec $ClientName curl -sS -o /dev/null --max-time 5 `
        --cacert /shared/ca.crt https://server.local/ | Out-Host
}

# --- Scenario 2: DNS NXDOMAIN. ---
# does-not-exist.local is in the .local zone but unregistered, so
# dnsmasq returns NXDOMAIN.
Capture-Scenario -Name "02_dns_nxdomain" -Action {
    docker exec $ClientName sh -c "curl -sS -o /dev/null --max-time 5 https://does-not-exist.local/ ; true" | Out-Host
}

# --- Scenario 3: TCP RST. ---
# server.local listens on 443 only; connecting to :9999 elicits a kernel RST.
Capture-Scenario -Name "03_tcp_rst" -Action {
    docker exec $ClientName sh -c "curl -sS -o /dev/null --max-time 3 http://server.local:9999/ ; true" | Out-Host
}

# --- Scenario 4: TLS certificate expired. ---
# With --cacert pointing at the test CA, curl now validates the chain
# successfully and ONLY THEN sees the leaf is expired -> OpenSSL
# error 10 (X509_V_ERR_CERT_HAS_EXPIRED) and TLS Alert 45.
Capture-Scenario -Name "04_tls_cert_expired" -Action {
    docker exec $ClientName sh -c "curl -sS -o /dev/null --max-time 5 --cacert /shared/ca.crt https://tls-broken.local:4443/ ; true" | Out-Host
}

# --- Scenario 5: WebSocket abnormal disconnect. ---
# ws-flaky aborts the TCP socket after WS_IDLE_KILL_SECONDS=3s.
# curl 8.18+ supports ws:// natively and keeps connection open for receive.
# timeout 5s allows server-side RST to fire (3s) before client gives up.
Capture-Scenario -Name "05_ws_idle_killed" -SettleMillis 1500 -Action {
    docker exec $ClientName sh -c "timeout 5 curl -v ws://ws-flaky.local:8080/ 2>&1 || true" | Out-Host
}

# --- Cleanup. ---
Cleanup-All

Write-Host "" 
Write-Host "Done. PCAPs are in:" -ForegroundColor Green
Write-Host "  $PcapDir"
Get-ChildItem $PcapDir -Filter "*.pcapng" | Select-Object Name, Length | Format-Table
