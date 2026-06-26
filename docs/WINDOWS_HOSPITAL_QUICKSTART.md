---
type: permanent
created: 2026-06-03
related_to: DEPLOYMENT_GUIDE.md
---

# 医院 Windows 现场快速上手

这份文档给医院技术人员使用，目标是先在 Windows 电脑上接入迈瑞监护仪并把 HL7 数据可靠保存到本地磁盘。

如果你不熟 Windows 命令、需要在现场从零操作，请优先看更详细的 `docs/WINDOWS_SITE_RUNBOOK.md`。

当前建议流程：**监护仪 -> Windows 采集端监听 6600 -> 本地 data 目录落盘**。

云端上传功能已经实现，但由于现场带宽和文件体积限制，上传会非常慢，当前不作为推荐使用方式，默认关闭。

---

## 1. 准备

需要：

- 一台 Windows 电脑，能用网线连接迈瑞监护仪
- Python 3.9 或更高版本，建议 3.9 到 3.11；安装时勾选 `Add Python to PATH`
- 本项目目录，建议放到 `C:\mindray_hl7_pipeline`

检查 Python：

```powershell
python --version
```

如果提示找不到 `python`，请重新安装 Python 并确认已加入 PATH。

---

## 2. 安装采集端

在 PowerShell 中执行：

```powershell
cd C:\mindray_hl7_pipeline
deploy\install.bat
```

安装脚本会：

- 不联网安装依赖。本地 HL7 采集不依赖第三方包
- 创建 `logs` 和 `data` 目录
- 检查 6600 端口是否可用
- 在桌面创建 `MindrayHL7Collector.bat`

---

## 3. 配置 Windows 网卡

先确认连接监护仪的网卡名称，常见是 `以太网 2`：

```powershell
Get-NetAdapter
```

管理员 PowerShell 中配置采集机 IP：

```powershell
netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192
```

检查是否生效：

```powershell
Get-NetIPConfiguration -InterfaceAlias "以太网 2"
```

应看到 IPv4 地址包含 `10.60.117.200`。

放行本机防火墙端口：

```powershell
netsh advfirewall firewall add rule name="Mindray-HL7-6600" dir=in action=allow protocol=TCP localport=6600
```

---

## 4. 配置监护仪

在迈瑞监护仪的 HL7 设置中配置：

- HL7 模式：客户端模式
- 服务器地址：`10.60.117.200`
- 端口：`6600`
- 打开波形发送 / 报警发送 / HL7 发送

监护仪是客户端模式，会主动连接 Windows 采集端。Windows 电脑必须先运行采集程序并监听 6600 端口。

---

## 5. 确认采集配置

打开：

```text
C:\mindray_hl7_pipeline\configs\client_config.json
```

关键项应为：

```json
{
  "listen_ip": "0.0.0.0",
  "listen_port": 6600,
  "data_dir": "data",
  "compress": true,
  "enable_ack": true,
  "upload": {
    "enabled": false
  }
}
```

注意：

- `enable_ack` 必须为 `true`，否则监护仪可能发一小段后停止。
- `upload.enabled` 当前应保持 `false`，先以本地落盘为准。

---

## 6. 启动采集

方式一：双击桌面 `MindrayHL7Collector.bat`。

方式二：PowerShell 手动启动：

```powershell
cd C:\mindray_hl7_pipeline
deploy\run_collector.bat
```

看到类似日志即表示采集端已启动：

```text
Listening on 0.0.0.0:6600
```

监护仪连接后应看到：

```text
Connected from ('10.60.117.196', xxxx)
```

停止采集：在窗口中按 `Ctrl+C`；如果提示是否终止批处理，输入 `Y` 后回车。

---

## 7. 验收本地数据

运行几分钟后，在项目目录执行：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 10 FullName,Length,LastWriteTime
```

预期出现并持续增长：

- `data\raw_hl7\...`：原始 HL7 报文
- `data\waveform_csv\...`：波形 CSV
- `data\numerics_csv\...`：生命体征数值 CSV，有对应数值报文时出现
- `data\events_csv\...`：报警/事件 CSV，有报警时才一定出现

这些文件可能包含设备号、病区/床位、采集时间等敏感信息。请按医院内部数据安全要求保存、复制和删除，不要通过微信、个人网盘或未批准的公网服务传输。

---

## 8. 常见问题

| 现象 | 检查 |
| --- | --- |
| 一直没有 `Connected from` | 网线、网卡名、采集机 IP、监护仪服务器地址、6600 防火墙 |
| 6600 端口被占用 | 运行 `Get-NetTCPConnection -LocalPort 6600 -State Listen` |
| 连上后没有数据文件 | 确认监护仪已开启 HL7/波形/报警发送，且有病人或导联信号 |
| 发一会就停 | 确认 `enable_ack` 是 `true` |
| 上传没有发生 | 这是当前推荐状态，`upload.enabled` 默认关闭 |

---

## 9. 打包给医院时不要包含

打包项目目录时，不要包含这些运行产物：

- `.git`
- `.venv`
- `data`
- `logs`
- `docs\sample_data`
- `__pycache__`
- `.DS_Store`
