# `web_l4l7` 抓包夹具

为 `web_l4l7_failures` profile 准备 5 份 canonical PCAP 的容器化抓包环境。
设计文档见 `docs/design/profile-web_l4l7_failures.md`。

## 5 份 PCAP 一览

| 文件 | 故障类型 | 核心 wire signature |
| --- | --- | --- |
| `01_web_ok.pcapng` | 无故障基线 | DNS A 成功 → TCP 三次握手 → TLS handshake 成功 → 200 OK |
| `02_dns_nxdomain.pcapng` | DNS NXDOMAIN | `does-not-exist.local` → DNS rcode=3 |
| `03_tcp_rst.pcapng` | TCP RST | 连接 `server.local:9999`（未监听）→ 内核回 RST |
| `04_tls_cert_expired.pcapng` | TLS 证书过期 | 服务器证书 `not_after = 2020-02-01` → 客户端 fatal alert (45) |
| `05_ws_idle_killed.pcapng` | WebSocket 异常断连 | server 3 秒后 `SO_LINGER=0` + `abort()` → TCP RST，无 WS Close 帧 |

## 一次性跑完

```powershell
# Windows PowerShell（Docker Desktop 启动后）
.\scripts\capture_all.ps1
```

```bash
# WSL / Linux / macOS
bash scripts/capture_all.sh
```

总用时 2-3 分钟（首次镜像 build 占大头；之后 ~30 秒）。
完成后 `pcaps/` 下应有 5 份 `*.pcapng`。

## 抓包技术细节（为什么这么搭）

- **dnsmasq**（10.5.0.10）：本地权威 DNS。`server.local` / `tls-broken.local` / `ws-flaky.local`
  解析到固定 IP；其它 `*.local` 全部 NXDOMAIN（`local=/local/` 配合）。
- **nginx**（10.5.0.20）：同一 image 跑两个 server block —— `:443` 用合法自签证书
  服 `server.local`，`:4443` 用 2020 年签发的过期证书服 `tls-broken.local`。证书在容器
  启动时用 Python `cryptography` 库现场生成（`gen_certs.py`），保证测试可重现。
- **ws-flaky**（10.5.0.30）：Python `websockets` echo server，`WS_IDLE_KILL_SECONDS=3`
  到点用 `SO_LINGER=0 + transport.abort()` 让内核直接发 TCP RST（不发 Close frame）。
  这是 NAT idle / LB worker 重启 / OOM-kill 的 wire signature。
- **client**（10.5.0.100）：`nicolaka/netshoot` 容器（curl + websocat 现成）。
  `--dns 10.5.0.10` 强制 DNS 走 dnsmasq，绕开 docker 内置 resolver。
- **抓包 sidecar**：`--network=container:web_l4l7_client` 共享 client 的 network
  namespace，`tshark -i eth0` 抓 client 进出的全部流量。`pcaps/` 目录 bind-mount
  到 host，pcap 直接落地。

## 网络故障排查

如果 `docker compose up --build` 卡在 `Pulling` 或直接 `Error failed to
resolve reference "docker.io/..."`，根因一般是 Docker Desktop 的代理
配置坏了或无法连 registry-1.docker.io。按先后顺序排查：

1. **代理进程没启**（最常见）：错误里出现 `connecting to 127.0.0.1:xxxx: connectex: No connection could be made...`
   说明 Docker 配了 HTTP 代理但代理没启。
   - 启动 Clash / V2Ray / 你平时用的代理，或
   - Settings → Resources → Proxies 改回 "System proxy" / "No proxy"
2. **Docker Hub 直连不通**：在 Docker Desktop → Settings → Docker Engine，JSON 里加：
   ```json
   "registry-mirrors": [
     "https://docker.m.daocloud.io",
     "https://dockerproxy.com"
   ]
   ```
   Apply & Restart 后验证：`docker pull alpine:3.20` 应 <30 秒完成。
3. **企业 MITM 证书**（公司笔记本常见）：Docker Desktop 默认不信任企业 CA。
   `Settings → Docker Engine` 里 `"allow-insecure-entitlements": true` 或
   安装企业根证书到 WSL2 发行版里。

## 脚本失败时的清理

`capture_all.{ps1,sh}` 自带 trap，脚本异常会自动 `docker compose down`。
万一遗留容器，手动清：

```powershell
docker rm -f web_l4l7_client web_l4l7_cap
docker compose -p web_l4l7 down --remove-orphans
```

## 改抓包参数

- 修改 `docker-compose.yml` 中 `WS_IDLE_KILL_SECONDS` 改 ws 死亡时机
- 修改 `dnsmasq/dnsmasq.conf` 的 `address=` 行加新域名
- 用环境变量覆盖镜像版本：
  `$env:NETSHOOT_IMAGE="nicolaka/netshoot:v0.14"; .\scripts\capture_all.ps1`
