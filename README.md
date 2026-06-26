# Mindray HL7 多模态生理数据采集系统

医院现场迈瑞监护仪 HL7 数据采集与本地落盘工具。

当前交付给医院方试运行时，推荐链路是：

**监护仪 -> Windows 采集端监听 6600 -> 本地 data 目录落盘**。

云端上传功能已有实现，但受现场带宽和文件体积限制，上传会非常慢，当前默认关闭，不建议作为试运行主流程。

本目录结构：
- **apps/client**：医院电脑上的采集端（监听 HL7/MLLP，落盘 CSV + 原始 HL7）
- **apps/server**：云端接收端（HTTP 上传文件，可选，不推荐当前试运行使用）
- **configs**：配置文件（如 `client_config.json`）
- **docs**：部署与验收文档
- **deploy**：Windows 一键安装与启动脚本
- **tests**：单元测试（38 个）

完整部署文档（超详细）见：
- 今日出差任务指引：[docs/ONSITE_TRIP_TASK_BRIEFING_20260626.md](docs/ONSITE_TRIP_TASK_BRIEFING_20260626.md)
- 现场负责人全貌与细节：[docs/ONSITE_OPERATOR_BRIEFING.md](docs/ONSITE_OPERATOR_BRIEFING.md)
- 现场照做版：[docs/WINDOWS_SITE_RUNBOOK.md](docs/WINDOWS_SITE_RUNBOOK.md)
- 医院 Windows 快速上手：[docs/WINDOWS_HOSPITAL_QUICKSTART.md](docs/WINDOWS_HOSPITAL_QUICKSTART.md)
- [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md)
- 接手要点（必读）：[docs/HANDOVER.md](docs/HANDOVER.md)

打包给医院方时建议使用：
```bash
tools/package_for_hospital.sh
```
该脚本会排除 `.git`、`.venv`、`data`、`logs`、`dist`、`__pycache__`、`.pytest_cache` 和 `docs/sample_data`。

---

## 系统架构

```
迈瑞监护仪                         医院 Windows 电脑
┌──────────────────┐              ┌─────────────────────────────┐
│ HL7 客户端模式   │  TCP/MLLP    │ collector.py                │
│ 服务器=采集机IP  │ ───────────> │ 监听 6600                   │
│ 端口=6600        │              │ 回 ACK，避免监护仪断流      │
└──────────────────┘              │ 写入 data/                  │
                                  │ 写入 logs/                  │
                                  └─────────────────────────────┘

主链路：监护仪 -> Windows 采集端监听(6600) -> 本地落盘
可选链路：本地文件 -> HTTP 上传 -> 云端服务(10000)，当前不推荐使用
```

### 两种运行模式

| 模式 | 程序 | 适用场景 |
|------|------|----------|
| **CLI 模式** | `collector.py` | 仅采集迈瑞监护仪，医院试运行推荐 |
| **GUI 模式** | `PhysRecorder.py` | 多设备同时采集，可选 |

---

## 目录结构

```
mindray_hl7_pipeline/
├── apps/
│   ├── client/
│   │   ├── collector.py         # CLI 采集器（仅监护仪，推荐）
│   │   ├── PhysRecorder.py      # GUI 主程序（多设备，可选）
│   │   ├── uploader.py          # 文件上传到云端（可选，不推荐试运行使用）
│   │   ├── hl7_parser.py        # HL7 解析（共享模块）
│   │   └── log_config.py        # 日志配置
│   └── server/
│       └── app.py               # 云端接收服务 (FastAPI)
├── configs/
│   └── client_config.json       # 客户端配置
├── deploy/
│   ├── install.bat              # 一键安装
│   ├── run_collector.bat        # 启动 CLI（自动重启）
│   ├── run_physrecorder.bat     # 启动 GUI（可选）
│   └── verify_install.py        # 安装检查
├── tests/
│   └── test_hl7_parser.py       # 单元测试（38个）
├── docs/
│   ├── ONSITE_TRIP_TASK_BRIEFING_20260626.md # 今日出差任务指引
│   ├── ONSITE_OPERATOR_BRIEFING.md # 现场负责人全貌与细节
│   ├── WINDOWS_HOSPITAL_QUICKSTART.md # 医院 Windows 快速上手
│   ├── WINDOWS_SITE_RUNBOOK.md # Windows 现场傻瓜式操作手册
│   ├── DEPLOYMENT_GUIDE.md      # 完整部署手册
│   └── HANDOVER.md              # 接手要点
├── logs/                        # 运行日志（自动创建）
├── data/                        # 采集数据（自动创建）
├── requirements.txt             # GUI 多设备完整依赖
└── pyproject.toml               # 项目配置
```

---

## 一、客户端（Windows 采集机）

### 1. 一键安装（推荐）

```powershell
cd C:\mindray_hl7_pipeline
deploy\install.bat
```

脚本会自动：检查 Python → 创建目录 → 验证安装 → 生成桌面快捷方式。

仅做本地 HL7 采集时，`collector.py` 不依赖第三方包。只有测试上传时才需要手动安装上传依赖：
```powershell
pip install -r apps\client\requirements.txt
```

### 2. 网络配置（首次部署）

给连接监护仪的网卡配同网段 IP：
```powershell
netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192
```

放行防火墙端口：
```powershell
netsh advfirewall firewall add rule name="Mindray-HL7-6600" dir=in action=allow protocol=TCP localport=6600
```

监护仪设置：
- HL7 模式 → **客户端模式**
- 服务器地址 → `10.60.117.200`
- 端口 → `6600`
- 开启波形发送 / 报警发送

### 3. 准备配置

编辑 `configs/client_config.json`：
- `listen_port`: 6600（需与监护仪一致）
- `data_dir`: `data`
- `compress`: `true`（生成 `.gz`）
- `device_id`: 可留空（自动从 MSH-3 解析）
- `enable_ack`: `true`（**必须开启**，否则监护仪断流）

### 4. 运行采集

**方式一：CLI 模式（仅监护仪，推荐）**

```powershell
deploy\run_collector.bat
```
程序崩溃会自动重启。停止时按 `Ctrl+C`；如果提示是否终止批处理，输入 `Y` 后回车。

也可以手动启动：
```powershell
python apps\client\collector.py --config configs\client_config.json
```

**方式二：GUI 模式（多设备，可选）**

如需多设备 GUI，再运行：
```powershell
deploy\run_physrecorder.bat
```
在 GUI 中设置监护仪端口（默认 6600）和其他设备，点击录制。

GUI 里的“上传数据”按钮同样受 `configs\client_config.json` 的 `upload.enabled` 控制。默认 `false` 时不会启动上传。

### 5. 落盘目录结构（默认）
```
data/
  raw_hl7/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM.hl7(.gz)
  waveform_csv/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM_<channel>.csv(.gz)
  events_csv/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM_alarm.csv(.gz)
  numerics_csv/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM_vitals.csv(.gz)
```

### 6. CSV 字段（波形）

| 字段 | 说明 |
|------|------|
| device_id | 设备 MAC |
| channel_code | 通道标识，如 `MDC_ECG_ELEC_POTL_I` |
| channel_name | 通道名称 |
| start_time / end_time | 时间戳（ISO 格式） |
| sample_rate | 采样率（Hz），如 ECG=500, PLETH=60 |
| resolution | 分辨率，物理值 = 原始值 × resolution |
| unit | 单位（mV、Hz 等） |
| samples | 原始采样值，`^` 分隔 |
| samples_count | 采样点数 |
| inop | 异常标记（如 32767 = 导联脱落） |

### 7. CSV 字段（生命体征数值）

| 字段 | 说明 |
|------|------|
| device_id | 设备 MAC |
| timestamp | 时间戳（ISO 格式） |
| code | MDC 代码，如 `147842` |
| name | 参数名称，如 `MDC_ECG_HEART_RATE` |
| value | 数值（HR、SpO2、RR、血压、体温等） |
| unit | 单位 |

### 8. CSV 字段（事件）

`device_id, event_code, event_name, event_phase, alarm_state, priority, timestamp`

---

## 二、云端服务（可选，不推荐当前试运行使用）

云端接收和自动上传代码保留在项目中，便于后续网络条件允许时扩展。但当前现场试运行应以本地落盘为准：

- 波形和原始 HL7 文件体积较大
- 医院现场到云服务器带宽可能有限
- 持续上传会非常慢，实际使用价值有限
- 原始 HL7 和 CSV 可能包含设备、病区、床位、时间戳等敏感信息

因此 `configs/client_config.json` 默认 `upload.enabled=false`。
如未来确实要启用上传，应先由医院方确认数据合规边界，并至少使用 HTTPS/VPN/API Key 等访问控制，不要把无鉴权 HTTP 接口暴露到公网。

### 0. 上传项目到云服务器

在本地终端执行（将 `<本项目路径>`、`user` 和 `<服务器IP>` 替换成实际值）：
```bash
scp -r <本项目路径>/mindray_hl7_pipeline/ user@<服务器IP>:/opt/mindray_hl7_pipeline
```

或者用 rsync（后续更新更方便，只传有变化的文件）：
```bash
rsync -avz --exclude 'data/' --exclude 'logs/' --exclude '.venv/' <本项目路径>/mindray_hl7_pipeline/ user@<服务器IP>:/opt/mindray_hl7_pipeline/
```

### 1. 安装依赖
```bash
cd /opt/mindray_hl7_pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/server/requirements.txt
```

### 2. 启动服务
```bash
cd /opt/mindray_hl7_pipeline/apps/server
DATA_DIR=/opt/mindray_hl7_pipeline/data uvicorn app:app --host 0.0.0.0 --port 10000
```

### 3. 设为系统服务（开机自启）

```bash
cat > /etc/systemd/system/mindray-hl7.service <<'EOF'
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

systemctl daemon-reload
systemctl enable --now mindray-hl7
```

### 4. 健康检查
```bash
curl http://127.0.0.1:10000/health
# {"status":"ok","time":"2026-01-25T..."}
```

### 5. 上传接口

`POST /upload`（multipart/form-data）
- `kind`: raw_hl7 / waveform_csv / numerics_csv / events_csv
- `device_id`: 可选
- `relative_path`: 可选，保留客户端目录结构
- `file`: 上传文件

服务会将文件保存到 `DATA_DIR` 下。

注意：该接口只是为后续扩展保留。试运行阶段不要启用；生产或跨网传输前必须补齐鉴权、传输加密、文件大小限制和留存策略。

### 6. API Key 鉴权（可选）

服务端设置环境变量 `API_KEY` 即可开启，不设置则不校验：
```bash
Environment=API_KEY=your-secret-key
```
客户端 `client_config.json` 中对应填入：
```json
"upload": {
  "api_key": "your-secret-key"
}
```

---

## 三、自动上传（可选，不推荐）

默认不要开启自动上传。只有在明确确认网络带宽、存储容量和数据合规要求后，再手动改为开启。

配置 `configs/client_config.json`：
```json
"upload": {
  "enabled": false,
  "base_url": "http://<server-ip>:10000",
  "api_key": "",
  "delete_after_upload": false,
  "min_age_seconds": 120,
  "run_in_background": true
}
```

如果把 `enabled` 改成 `true` 且 `run_in_background=true`，collector 启动时会自动拉起上传线程。当前不建议这么做。

也可以单独运行上传器（循环上传）：
```powershell
python apps\client\uploader.py --config configs\client_config.json
```

---

## 四、日志

程序运行日志在 `logs/` 目录下，自动轮转（10MB × 5 份）：

- `logs/physrecorder.log` — GUI 模式日志
- `logs/collector.log` — CLI 模式日志

---

## 五、测试

```bash
pytest tests/ -v
```

覆盖 HL7 时间戳解析、单位映射、设备 ID 提取、MLLP 帧解码、ACK 构建、波形/数值参数/事件解析，共 38 个用例。

---

## 六、客户端完整配置说明

`configs/client_config.json` 字段：

```jsonc
{
  "listen_ip": "0.0.0.0",          // 监听地址
  "listen_port": 6600,             // 监听端口（需与监护仪一致）
  "device_id": "",                 // 留空则自动从 HL7 消息解析
  "data_dir": "data",              // 本地数据目录
  "split_minutes": 1,              // CSV 文件切割间隔（分钟）
  "compress": true,                // 启用 gzip 压缩
  "enable_ack": true,              // 回复 ACK（必须开启，否则监护仪断流）
  "write_raw_hl7": true,           // 保存原始 HL7 帧
  "write_waveforms": true,         // 保存波形 CSV
  "write_events": true,            // 保存事件 CSV
  "ack_app": "RECV",               // ACK 应用名
  "ack_facility": "RECV",          // ACK 设施名
  "upload": {
    "enabled": false,              // 是否开启云端上传
    "base_url": "http://<服务器IP>:10000",
    "api_key": "",                 // 可选 API Key
    "delete_after_upload": false,  // 上传后是否删除本地文件
    "timeout_seconds": 15,         // 上传超时
    "retry_seconds": 30,           // 重试间隔
    "min_age_seconds": 120,        // 文件写入 2 分钟后才上传
    "run_in_background": true      // collector 自动启动上传线程
  }
}
```

---

## 七、常见问题

| 现象 | 排查 |
|------|------|
| 没有 `Connected from ...` | 检查 IP 同网段、端口一致、防火墙放行 |
| 连上了没数据 | 监护仪是否开启波形发送、是否有病人/导联 |
| 上传没有发生 | 当前默认关闭上传，这是推荐状态 |
| 必须测试上传 | `upload.enabled` 改为 true 后，再检查云端 10000 和 `base_url` |
| 监护仪发一会就停 | `enable_ack` 必须为 true，不回 ACK 监护仪会断流 |

更多排查方法见 [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) 第 9 节。

---

## English Quick Start

- **GUI mode (all devices):**
  `python apps\client\PhysRecorder.py`
- **CLI mode (monitor only):**
  `python apps\client\collector.py --config configs\client_config.json`
- **Server:**
  `uvicorn app:app --host 0.0.0.0 --port 10000`
- **Upload endpoint:** `POST /upload` (multipart, optional)
- **Health check:** `GET /health`
