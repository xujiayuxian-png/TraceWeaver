---
description: 采集与校验 ailink5gs / UERANSIM 5GC 测试抓包
---

# 5GC 测试抓包 workflow

适用场景：

- 在 `ailink5gs` + `UERANSIM` 环境中复现 5GC 注册 / PDU / SBI / PFCP 相关测试场景
- 需要把抓包结果落到 `tests/fixtures/pcap/`
- 需要同时保留用户数据、故障触发方式和样本语义

## 0. 环境前提

- 本机工作目录：`/home/ailink/code/TraceWeaver`
- UERANSIM 目录：`/home/ailink/UERANSIM`
- 远端核心网：`ailink@192.168.30.193`
- MongoDB：`ailink5gs.subscribers`
- 默认 UE：`001010000000210`
- `ailink5gs` SBI 默认端口：`7777`

## 1. 基础检查

先确认本地没有残留进程、没有残留抓包状态：

```bash
pgrep -af '/home/ailink/UERANSIM/build/nr-(gnb|ue)' || true
test -f /home/ailink/code/TraceWeaver/.traceweaver/capture.env && cat /home/ailink/code/TraceWeaver/.traceweaver/capture.env || echo no-active-capture
ls -lh /home/ailink/code/TraceWeaver/tests/fixtures/pcap
```

再确认远端服务状态：

```bash
sshpass -p 'ailink' ssh -o StrictHostKeyChecking=no ailink@192.168.30.193 "/opt/ailink5gs/bin/status_all.sh | egrep 'amf|ausf|udm|smf|upf|UNIT' || true"
```

## 2. 常用采集脚本

统一使用：

```bash
bash /home/ailink/code/TraceWeaver/scripts/traceweaver_test_data.sh <command>
```

常用命令：

- `capture-start <name>`
- `capture-stop <output>`
- `gnb-start`
- `gnb-stop`
- `ue-start`
- `ue-stop`
- `subscriber-export <imsi> <path>`
- `subscriber-import <json>`
- `subscriber-show <imsi>`
- `validate <pcap>`

## 3. 正常场景采集模板

```bash
export AILINK5GS_PASS='ailink' AILINK5GS_SUDO_PASS='ailink' UE_CFG='/home/ailink/UERANSIM/config/custom-ue-registration-only.yaml'
PCAP='/home/ailink/code/TraceWeaver/tests/fixtures/pcap/01_registration_success.pcapng'

bash scripts/traceweaver_test_data.sh capture-start 01_registration_success
bash scripts/traceweaver_test_data.sh gnb-start
sleep 5
bash scripts/traceweaver_test_data.sh ue-start
sleep 25
bash scripts/traceweaver_test_data.sh capture-stop "$PCAP"
bash scripts/traceweaver_test_data.sh ue-stop || true
bash scripts/traceweaver_test_data.sh gnb-stop || true
bash scripts/traceweaver_test_data.sh validate "$PCAP"
```

## 4. 故障场景采集关键点

### 4.1 涉及停网元时

**必须先停看门狗**：

```bash
sshpass -p 'ailink' ssh -o StrictHostKeyChecking=no ailink@192.168.30.193 "printf '%s\n' 'ailink' | sudo -S -p '' systemctl stop 5gswatching.timer"
```

然后再停目标 NF，例如：

```bash
sshpass -p 'ailink' ssh -o StrictHostKeyChecking=no ailink@192.168.30.193 "printf '%s\n' 'ailink' | sudo -S -p '' systemctl stop ailink5gs-upfd.service"
```

采完后恢复：

```bash
sshpass -p 'ailink' ssh -o StrictHostKeyChecking=no ailink@192.168.30.193 "printf '%s\n' 'ailink' | sudo -S -p '' systemctl start ailink5gs-upfd.service; printf '%s\n' 'ailink' | sudo -S -p '' systemctl start 5gswatching.timer"
```

### 4.2 关注 SBI 流量时

不要只看默认 `http2` 过滤，应优先检查 `7777` 端口：

```bash
tshark -d tcp.port==7777,http2 -r file.pcapng -Y 'http2'
```

常用字段：

```bash
tshark -d tcp.port==7777,http2 -r file.pcapng -Y 'http2' -T fields \
  -e frame.number -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport \
  -e http2.streamid -e http2.type -e _ws.col.Info
```

### 4.3 构造 partial visibility 样本时

如果要构造 `15_partial_visibility_multi_host.pcapng` 这类“只看到 N2 + SBI，缺少完整下游视角”的样本，可以在远端主机上直接限制抓包端口：

```bash
sudo tcpdump -i any -s 0 -U 'port 38412 or port 7777' -w /tmp/15_partial_visibility_multi_host.pcapng
```

这个过滤会保留：

- `38412` 上的 `NGAP`
- `7777` 上的 `SBI/HTTP2`

同时天然缺少：

- 完整 `PFCP` 细节
- 非目标端口上的其它可见性

采完后建议使用以下命令确认样本语义：

```bash
tshark -d tcp.port==7777,http2 -r 15_partial_visibility_multi_host.pcapng -Y 'ngap || http2 || pfcp'
```

## 5. UERANSIM CLI 常用命令

列出节点：

```bash
/home/ailink/UERANSIM/build/nr-cli --dump
```

UE 常用命令：

```bash
/home/ailink/UERANSIM/build/nr-cli imsi-001010000000210 -e 'status'
/home/ailink/UERANSIM/build/nr-cli imsi-001010000000210 -e 'ps-list'
/home/ailink/UERANSIM/build/nr-cli imsi-001010000000210 -e 'ps-establish IPv4 -n cmnet'
/home/ailink/UERANSIM/build/nr-cli imsi-001010000000210 -e 'ps-release-all'
/home/ailink/UERANSIM/build/nr-cli imsi-001010000000210 -e 'deregister normal'
```

gNB 常用命令：

```bash
/home/ailink/UERANSIM/build/nr-cli UERANSIM-gnb-1-1-1 -e 'ue-list'
/home/ailink/UERANSIM/build/nr-cli UERANSIM-gnb-1-1-1 -e 'ue-release 1'
```

## 6. 采后校验

最小校验：

```bash
bash /home/ailink/code/TraceWeaver/scripts/traceweaver_test_data.sh validate /home/ailink/code/TraceWeaver/tests/fixtures/pcap/<file>.pcapng
```

进一步校验：

```bash
tshark -r file.pcapng -Y 'nas-5gs' -T fields -e nas_5gs.mm.message_type -e nas_5gs.sm.message_type | sort | uniq -c

tshark -r file.pcapng -Y 'ngap' -T fields -e ngap.procedureCode | sort | uniq -c

tshark -d tcp.port==7777,http2 -r file.pcapng -Y 'http2' -V | egrep -i 'header: :path|header: :method|header: :status'

tshark -r file.pcapng -Y 'pfcp' -T fields -e pfcp.msg_type | sort | uniq -c
```

## 7. 采后文档维护

每采完一份 canonical 样本，都要更新：

- `plan/test-pcap-catalog.md`

至少记录：

- 文件名
- 场景语义
- 是否正式 / 候选
- 关键证据
- 是否存在注意事项（例如自动重注册、只是 forwarding failure 等）

## 8. 当前已知注意事项

- `05` 更像 `SM forwarding failure / PAYLOAD_NOT_FORWARDED`
- `10` CLI 去注册后，UE 可能因为配置继续自动注册
- `13` 原始版比 clean/manual 版本更稳定
- `06` 目前仍未拿到真正教科书式的 Security Mode Reject
