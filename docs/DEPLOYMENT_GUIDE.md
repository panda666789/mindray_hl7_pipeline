# 迈瑞 HL7 项目：实现、交互与部署手册（超详细版）

这份文档的目标是：
- 让你在**不问别人**的情况下，自己就能部署起来
- 让后来的人拿到这份文档就能接手维护
- 讲清楚：客户端做什么、服务端做什么、两者怎么交互

如果你只想快速跑通，直接看第 3 节和第 5 节。

接手必读（更短）：`docs/HANDOVER.md`

---

## 1. 先用一句人话讲清楚这个项目

这套系统分两端：

1) 医院现场电脑（客户端 / 采集端）
- 接在监护仪旁边
- 监听监护仪发来的 HL7 数据（TCP + MLLP）
- 一边回 ACK 保持数据不断流
- 一边把数据落盘（CSV + 原始 HL7）
- 再把文件上传到云服务器

2) 云服务器（服务端 / 接收端）
- 提供一个 HTTP 接口（`POST /upload`）
- 接收客户端上传的文件
- 存到云服务器磁盘上

一句话总结链路：

监护仪 -> 客户端监听(6600) -> 本地落盘 -> 上传 -> 云端服务(10000) -> 云端落盘

---

## 2. 项目目录结构（你要改代码就看这里）

项目根目录：`mindray_hl7_pipeline/`

关键文件：

- 客户端采集：`mindray_hl7_pipeline/apps/client/collector.py`
- 客户端上传：`mindray_hl7_pipeline/apps/client/uploader.py`
- 客户端配置：`mindray_hl7_pipeline/configs/client_config.json`
- 服务端接口：`mindray_hl7_pipeline/apps/server/app.py`
- 服务端依赖：`mindray_hl7_pipeline/apps/server/requirements.txt`
- 客户端依赖：`mindray_hl7_pipeline/apps/client/requirements.txt`

---

## 3. 数据如何交互（一定要理解的 4 个点）

### 3.1 监护仪是“客户端模式”

这点非常关键：

- 监护仪会主动连出
- 我们的医院现场电脑必须“监听端口”等它来连
- 云服务器不能直接连监护仪（不在一个内网）

所以采集端必须部署在现场电脑上。

### 3.2 监护仪发的是 HL7 v2.6 + MLLP

不是普通文本流，而是带帧的：

- 帧起始：`0x0b`
- 帧结束：`0x1c 0x0d`

`collector.py` 里已经按这个规则拆帧。

### 3.3 ACK 必须回，不回就断流

你已经现场验证过：

- 不回 ACK，监护仪只发很短一段就停
- 回 ACK，就会持续发

`collector.py` 默认开启 ACK（`enable_ack: true`）。

### 3.4 我们选择“落盘为主，上传为辅”

策略是：

1) 先可靠落盘（CSV + 原始 HL7）
2) 再异步上传

这样即使断网，也不会丢数据。

---

## 4. 部署前准备清单（照着核对）

### 4.1 你需要准备的两台机器

1) 医院现场电脑（Windows）
- 能接监护仪网线
- 能出网访问云服务器

2) 云服务器（Linux）
- 能对外提供一个端口（我们用 10000）

### 4.2 必须确认的参数（已知值）

来自现场确认：

- 监护仪 IP：`10.60.117.196`
- 子网掩码：`255.255.255.192`（/26）
- 网关：`10.60.117.193`
- HL7 端口（监护仪侧配置）：`6600`
- 云端服务端口（我们改成）：`10000`

建议采集机 IP（同网段即可）：

- 采集机 IP：`10.60.117.200`
- 子网掩码：`255.255.255.192`

---

## 5. 医院现场电脑部署（一步一步照做）

下面所有命令默认在 PowerShell 里执行。

### 5.1 给网卡配置同网段 IP（非常关键）

先找到连接监护仪的网卡名称（你现场是 `以太网 2`）。

设置 IP：

```powershell
netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192
```

检查是否生效：

```powershell
Get-NetIPConfiguration -InterfaceAlias "以太网 2"
```

你应该能看到：
- IPv4Address = `10.60.117.200`

### 5.2 放行本机防火墙的 6600 端口（建议做）

管理员 PowerShell：

```powershell
netsh advfirewall firewall add rule name="Mindray-HL7-6600" dir=in action=allow protocol=TCP localport=6600
```

### 5.3 配置监护仪（让它连到采集机）

在监护仪 HL7 设置中：

- HL7 模式：客户端模式
- 服务器地址：`10.60.117.200`
- 端口：`6600`
- 打开：波形发送 / 报警发送（如果有开关）

如果这里填错，后面一定收不到数据。

### 5.4 安装 Python（如果还没装）

检查：

```powershell
python --version
```

建议 Python 3.9+（3.10/3.11 都可以）。

### 5.5 放置项目代码

把整个目录 `mindray_hl7_pipeline/` 放到现场电脑，比如：

- `C:\mindray_hl7_pipeline`

后续所有路径以这个为准。

### 5.6 安装依赖（客户端）

```powershell
cd C:\mindray_hl7_pipeline
pip install -r .\apps\client\requirements.txt
```

说明：
- `collector.py` 本身只用标准库
- 但如果你要上传，需要 `requests`

### 5.7 修改客户端配置（最重要）

编辑文件：`C:\mindray_hl7_pipeline\configs\client_config.json`

至少改这几项：

```json
{
  "listen_ip": "0.0.0.0",
  "listen_port": 6600,
  "data_dir": "data",
  "enable_ack": true,
  "upload": {
    "enabled": true,
    "base_url": "http://<你的云服务器IP>:10000",
    "delete_after_upload": false,
    "min_age_seconds": 120,
    "run_in_background": true
  }
}
```

关键解释：
- `listen_port` 必须和监护仪填的一致（6600）
- `base_url` 必须写云服务器地址和端口（10000）
- `enabled` 不开就不会上传

### 5.8 启动采集端（开始收数）

在 PowerShell：

```powershell
cd C:\mindray_hl7_pipeline
python .\apps\client\collector.py --config .\configs\client_config.json
```

看到类似日志就对了：

- Listening on 0.0.0.0:6600
- Connected from (10.60.117.196, xxxx)
- Uploader thread started（如果开启上传）

### 5.9 如何判断“真的收到数据了”

采集端落盘目录在：

- `C:\mindray_hl7_pipeline\data\`

你可以这样看文件是否在增长：

```powershell
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 10 FullName,Length,LastWriteTime
```

重点看这三类目录：

- `data\raw_hl7\...`
- `data\waveform_csv\...`
- `data\events_csv\...`

### 5.10 如何停止

在运行窗口按：

- `Ctrl + C`

---

## 6. 云服务器部署（一步一步照做）

以下示例以 Linux 为主（Ubuntu/CentOS 都类似）。

### 6.1 开放云服务器端口 10000

你需要确保安全组 / 防火墙放行 TCP 10000。

这是上传能否成功的前提。

### 6.2 放置项目代码

把 `mindray_hl7_pipeline/` 上传到云服务器，例如：

- `/opt/mindray_hl7_pipeline`

### 6.3 安装依赖（服务端）

```bash
cd /opt/mindray_hl7_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
```

### 6.4 启动服务端（10000 端口）

```bash
cd /opt/mindray_hl7_pipeline/apps/server
DATA_DIR=/opt/mindray_hl7_pipeline/data uvicorn app:app --host 0.0.0.0 --port 10000
```

说明：
- `DATA_DIR` 是云端落盘目录
- 你可以按需改成别的路径

### 6.5 健康检查（确认服务真的起来了）

在云服务器本机执行：

```bash
curl http://127.0.0.1:10000/health
```

返回类似：

```json
{"status":"ok","time":"2026-01-25T..."}
```

如果本机都不通，就先别让客户端连。

---

## 7. 客户端与服务端的交互协议（给开发者看的）

### 7.1 客户端 -> 服务端接口

接口：
- `POST /upload`
- Content-Type: `multipart/form-data`

表单字段：
- `kind`: `raw_hl7` / `waveform_csv` / `events_csv`
- `device_id`: 可选
- `relative_path`: 建议传（保留目录结构）
- `file`: 文件本体

### 7.2 服务端保存逻辑

服务端代码在：`mindray_hl7_pipeline/apps/server/app.py`

保存策略：

1) 如果传了 `relative_path`
- 直接按这个路径落到 `DATA_DIR` 下

2) 如果没传
- 自动按时间分桶到：
  - `DATA_DIR/<kind>/YYYY/MM/DD/HH/`

---

## 8. 落盘格式说明（科研人员最关心）

### 8.1 波形 CSV（waveform_csv）

表头：

- `device_id`
- `channel_code`
- `channel_name`
- `start_time`
- `end_time`
- `sample_rate`
- `resolution`
- `unit`
- `samples`
- `samples_count`
- `inop`

其中：
- `samples` 是 caret 分隔的原始值（例如 `80^88^92^...`）
- 物理值换算：`物理值 = 原始值 * resolution`
- 单点时间戳：`ts = start_time + index / sample_rate`

### 8.2 事件 CSV（events_csv）

表头：

- `device_id`
- `event_code`
- `event_name`
- `event_phase`
- `alarm_state`
- `priority`
- `timestamp`

### 8.3 原始 HL7（raw_hl7）

这是“真相来源”，建议长期保留，便于追溯。

---

## 9. 常见问题排查（出问题就照着对）

### 9.1 监护仪没有连上（最常见）

现象：
- 采集端一直没有 `Connected from ...`

检查顺序：

1) 采集机 IP 是否在同网段（10.60.117.200/26）
2) 监护仪服务器地址是否填了采集机 IP
3) 端口是否一致（6600）
4) 防火墙是否放行 6600
5) 网线是否真的接在那块网卡上

### 9.2 连上了但没数据

检查：

1) 监护仪是否开启“波形发送/HL7发送”
2) 是否有病人/导联已佩戴
3) 是否被别的程序占用了 6600 端口

查看端口占用（Windows）：

```powershell
Get-NetTCPConnection -LocalPort 6600 -State Listen
```

### 9.3 本地有数据但没上传

检查：

1) `upload.enabled` 是否为 `true`
2) `base_url` 是否写成了 `http://<server-ip>:10000`
3) 云服务器 10000 是否放行
4) 云端 `curl /health` 是否正常

### 9.4 上传慢 or 看起来没动静

这是设计如此：

- 上传器会跳过“刚写过的文件”
- 只有超过 `min_age_seconds`（默认 120 秒）才上传

这是为了避免上传到一半文件还在写。

---

## 10. 修改项目时你最可能会改的地方

### 10.1 改监听端口（监护仪端口）

改这里：
- `mindray_hl7_pipeline/configs/client_config.json` -> `listen_port`

同时必须：
- 监护仪上也改成同一个端口

### 10.2 改云端端口

你现在用的是 10000。

如果要改：

1) 改服务端启动命令里的 `--port`
2) 改客户端配置里的 `upload.base_url`

### 10.3 想把 samples 改成“每行一个点”

你需要改：
- `mindray_hl7_pipeline/apps/client/collector.py`

关键词搜索：
- `write_row`
- `samples`
- `samples_count`

---

## 11. 一份“最小可用部署清单”（照抄就能跑）

### 11.1 云服务器

```bash
cd /opt/mindray_hl7_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
cd server
DATA_DIR=/opt/mindray_hl7_pipeline/data uvicorn app:app --host 0.0.0.0 --port 10000
```

### 11.2 医院采集机

```powershell
netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192
netsh advfirewall firewall add rule name="Mindray-HL7-6600" dir=in action=allow protocol=TCP localport=6600

cd C:\mindray_hl7_pipeline
pip install -r .\apps\client\requirements.txt
python .\apps\client\collector.py --config .\configs\client_config.json
```

并确保：
- 监护仪 HL7 服务器地址 = `10.60.117.200`
- 监护仪 HL7 端口 = `6600`
- `client_config.json` 中 `upload.enabled = true`
- `base_url = http://<云服务器IP>:10000`

---

## 12. 你接下来最应该做的两件事（强烈建议）

1) 我可以继续帮你补两样东西：
- Windows 开机自启动（或服务化）
- Linux systemd 常驻服务（云端）

2) 跑一次真实链路验收：
- 云端先启动
- 采集端再启动
- 看云端 `data/` 是否出现文件

如果你愿意，我下一步就直接把：
- `systemd` 服务文件
- Windows 自启动脚本
- 验收 checklist
一次性补齐。

---

## 13. 通用流程 + 预期结果（方便日后快速恢复）

> 这部分是给“过一段时间再回来继续做”的你用的。  
> 直接按步骤走，能快速确认链路是否恢复。

### 13.1 恢复/启动流程（现场采集端）

**步骤 A：确认物理连接**
1. 监护仪网线插到采集机的那块网卡（通常是“以太网 2”）。
2. `ipconfig` 中该网卡应显示“已连接”。

**预期结果**
- 以太网 2 显示“媒体已连接”

**步骤 B：确认采集机 IP**
1. 运行：
   ```powershell
   Get-NetIPConfiguration -InterfaceAlias "以太网 2"
   ```
2. 如果没有 `10.60.117.200`，执行：
   ```powershell
   netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192
   ```

**预期结果**
- IPv4Address 显示 `10.60.117.200`

**步骤 C：确认监护仪 HL7 设置**
1. HL7 模式：客户端模式  
2. 服务器地址：`10.60.117.200`  
3. 端口：`6600`  
4. 打开“波形发送/报警发送”

**预期结果**
- 监护仪开始尝试连接采集机

**步骤 D：启动采集端程序**
```powershell
cd C:\mindray_hl7_pipeline
python .\apps\client\collector.py --config .\configs\client_config.json
```

**预期结果**
- 窗口出现 `Listening on 0.0.0.0:6600`
- 监护仪接入后出现 `Connected from 10.60.117.196`

**步骤 E：确认本地落盘**
```powershell
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,Length,LastWriteTime
```

**预期结果**
- `data\raw_hl7\...` 有文件
- `data\waveform_csv\...` 有文件
- `data\events_csv\...` 有文件（如果触发报警）

---

### 13.2 恢复/启动流程（云端接收端）

**步骤 A：启动服务**
```bash
cd /opt/mindray_hl7_pipeline/apps/server
DATA_DIR=/opt/mindray_hl7_pipeline/data uvicorn app:app --host 0.0.0.0 --port 10000
```

**预期结果**
- 控制台提示正在监听 10000 端口

**步骤 B：健康检查**
```bash
curl http://127.0.0.1:10000/health
```

**预期结果**
- 返回 `{"status":"ok", ...}`

**步骤 C：确认上传**
当采集端上传后，在云端：
```bash
ls -la /opt/mindray_hl7_pipeline/data
```

**预期结果**
- 出现 `raw_hl7/`、`waveform_csv/`、`events_csv/` 目录并持续增长

---

### 13.3 常见“恢复失败”原因速查

1. **网线没插对**：以太网 2 仍显示“断开”
2. **采集端 IP 丢失**：重启后静态 IP 被清掉
3. **监护仪配置被改**：服务器 IP/端口不一致
4. **防火墙阻断 6600**：采集端监听不到连接
5. **云端端口未放行 10000**：上传失败

---

### 13.4 一句总结

只要满足下面 4 个条件，就一定能恢复采集：

1) 采集机 IP = 10.60.117.200/26  
2) 监护仪 HL7 = 客户端模式 + 服务器 IP/端口正确  
3) 采集端程序运行中（监听 6600）  
4) 云端 10000 端口对外开放  

---

## 14. 后台部署/服务化（当前实际部署方式）

> 下面是“稳定后台运行”的标准做法。  
> 医院采集端用**计划任务 + 自动重启脚本**，云端用 **systemd**。

### 14.1 医院采集端（Windows）

**A. 生成自动重启脚本（带日志）**
```powershell
New-Item -ItemType Directory E:\mindray_hl7_pipeline\logs -Force | Out-Null

@'
@echo off
set PY=C:\ProgramData\miniconda3\python.exe
set ROOT=E:\mindray_hl7_pipeline
cd /d %ROOT%
:loop
"%PY%" "%ROOT%\apps\client\collector.py" --config "%ROOT%\configs\client_config.json" >> "%ROOT%\logs\collector.log" 2>>&1
timeout /t 5 >nul
goto loop
'@ | Set-Content E:\mindray_hl7_pipeline\apps\client\run_collector_loop.cmd -Encoding ASCII
```
> 如果 Python 路径不同，用 `where python` 或 `python -V` 确认后替换 `PY=...`。

**B. 创建计划任务（登录后自动运行）**
```powershell
SCHTASKS /Create /TN "MindrayHL7Collector" /TR "E:\mindray_hl7_pipeline\apps\client\run_collector_loop.cmd" /SC ONLOGON /RU "desktop-0mald86\wl" /RL HIGHEST /F /IT
```
> 把用户名换成 `whoami` 的输出。

**C. 立即启动**
```powershell
SCHTASKS /Run /TN "MindrayHL7Collector"
```

**D. 查看日志**
```powershell
Get-Content E:\mindray_hl7_pipeline\logs\collector.log -Tail 50
```

**说明**
- 这套方式“登录后自动运行”；若电脑登出，任务会停。  
- 若必须“不开机登录也运行”，需要用同账号+密码创建 ONSTART 任务。

### 14.2 云端服务（Linux / systemd）

**A. 创建 systemd 服务**
```bash
cat >/etc/systemd/system/mindray-hl7.service <<'EOF'
[Unit]
Description=Mindray HL7 Ingest Service
After=network.target

[Service]
WorkingDirectory=/opt/mindray_hl7_pipeline/apps/server
Environment=DATA_DIR=/opt/mindray_hl7_pipeline/data
ExecStart=/opt/mindray_hl7_pipeline/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 10000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
```

**B. 启动 + 开机自启**
```bash
systemctl daemon-reload
systemctl enable mindray-hl7
systemctl start mindray-hl7
systemctl status mindray-hl7
```

**C. 查看日志**
```bash
journalctl -u mindray-hl7 -f
```

---

## 15. 上传数据验收（确认数据真的来自监护仪）

> 目标：确认上传到云端的数据结构正确、内容合理、确实是监护仪波形/事件。

### 15.1 云端检查（推荐）

**A. 看是否有文件进入云端**
```bash
ls -la /opt/mindray_hl7_pipeline/data
```
预期：出现 `raw_hl7/`、`waveform_csv/`、`events_csv/` 目录。

**B. 抽查原始 HL7（确认 MSH/OBX）**
```bash
zcat /opt/mindray_hl7_pipeline/data/raw_hl7/*/*/*/*/*.hl7.gz | head -n 20
```
预期能看到：
- `MSH|...|MINDRAY_...`
- `ORU^R01` / `ORU^R40`
- `OBX|...|MDC_ECG_ELEC_POTL_*` 等

**C. 抽查波形 CSV**
```bash
zcat /opt/mindray_hl7_pipeline/data/waveform_csv/*/*/*/*/*.csv.gz | head -n 5
```
预期字段包含：
`device_id, channel_code, sample_rate, resolution, samples`

**D. 抽查事件 CSV**
```bash
zcat /opt/mindray_hl7_pipeline/data/events_csv/*/*/*/*/*.csv.gz | head -n 5
```

### 15.2 采集端本地检查（可选）

```powershell
Get-ChildItem E:\mindray_hl7_pipeline\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,Length,LastWriteTime
```

### 15.3 重点验证点（最关键）

1) `device_id` 是你现场看到的 `00A037000000`  
2) ECG 采样率 `500 Hz`  
3) PLETH 采样率 `60 Hz`  
4) RESP 采样率 `256 Hz`  
5) HL7 报文里 `MSH` 发送端为 `MINDRAY`  

只要这些都满足，就可以确定：  
**上传的数据确实来自监护仪，且被正确接收。**
