# Mindray HL7 多模态生理数据采集系统

医院现场多设备数据采集 + 云端存储的完整解决方案。

本目录结构：
- **apps/client**：医院电脑上的采集端（监听 HL7/MLLP，落盘 CSV + 原始 HL7，多设备 GUI）
- **apps/server**：云端接收端（HTTP 上传文件）
- **configs**：配置文件（如 `client_config.json`）
- **docs**：部署与验收文档
- **deploy**：Windows 一键安装与启动脚本
- **tests**：单元测试（37 个）

完整部署文档（超详细）见：
- [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md)
- 接手要点（必读）：[docs/HANDOVER.md](docs/HANDOVER.md)

---

## 系统架构

```
医院 Windows 电脑                              云服务器
┌─────────────────────────────┐          ┌──────────────────┐
│  PhysRecorder (GUI)         │          │  app.py (FastAPI) │
│  ├─ 迈瑞监护仪 (HL7/MLLP)  │  HTTP    │  端口 10000       │
│  ├─ PPG 蓝牙手环 (BLE)      │ ──────> │  接收上传文件     │
│  ├─ EEG 脑电 (串口)         │  上传    │  落盘到 data/     │
│  ├─ GSR 皮电 (HID)          │          └──────────────────┘
│  ├─ 摄像头 (OpenCV)         │
│  └─ HUB 8通道 (串口)        │
│                             │
│  数据落盘到 data/            │
│  日志写入 logs/              │
└─────────────────────────────┘

数据链路：监护仪 -> 客户端监听(6600) -> 本地落盘 -> 上传 -> 云端服务(10000) -> 云端落盘
```

### 两种运行模式

| 模式 | 程序 | 适用场景 |
|------|------|----------|
| **GUI 模式** | `PhysRecorder.py` | 多设备同时采集（推荐） |
| **CLI 模式** | `collector.py` | 仅采集迈瑞监护仪 |

---

## 目录结构

```
mindray_hl7_pipeline/
├── apps/
│   ├── client/
│   │   ├── PhysRecorder.py      # GUI 主程序（所有设备）
│   │   ├── collector.py         # CLI 采集器（仅监护仪）
│   │   ├── uploader.py          # 文件上传到云端
│   │   ├── hl7_parser.py        # HL7 解析（共享模块）
│   │   └── log_config.py        # 日志配置
│   └── server/
│       └── app.py               # 云端接收服务 (FastAPI)
├── configs/
│   └── client_config.json       # 客户端配置
├── deploy/
│   ├── install.bat              # 一键安装
│   ├── run_physrecorder.bat     # 启动 GUI
│   ├── run_collector.bat        # 启动 CLI（自动重启）
│   └── verify_install.py        # 安装检查
├── tests/
│   └── test_hl7_parser.py       # 单元测试（37个）
├── docs/
│   ├── DEPLOYMENT_GUIDE.md      # 超详细部署手册
│   ├── HANDOVER.md              # 接手要点
│   └── sample_data/             # 示例数据
├── logs/                        # 运行日志（自动创建）
├── data/                        # 采集数据（自动创建）
├── requirements.txt             # Python 依赖
└── pyproject.toml               # 项目配置
```

---

## 一、客户端（Windows 采集机）

### 1. 一键安装（推荐）

```powershell
cd C:\mindray_hl7_pipeline
deploy\install.bat
```

脚本会自动：检查 Python → 安装依赖 → 创建目录 → 验证安装 → 生成桌面快捷方式。

也可以手动安装依赖：
```powershell
pip install -r requirements.txt
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

**方式一：GUI 模式（多设备，推荐）**

双击桌面 `PhysRecorder.bat`，或：
```powershell
deploy\run_physrecorder.bat
```
在 GUI 中设置监护仪端口（默认 6600）和其他设备，点击录制。

**方式二：CLI 模式（仅监护仪）**

```powershell
deploy\run_collector.bat
```
程序崩溃会自动重启，按 `Ctrl+C` 停止。

也可以手动启动：
```powershell
python apps\client\collector.py --config configs\client_config.json
```

### 5. 落盘目录结构（默认）
```
data/
  raw_hl7/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM.hl7(.gz)
  waveform_csv/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM_<channel>.csv(.gz)
  events_csv/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM_alarm.csv(.gz)
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

### 7. CSV 字段（事件）

`device_id, event_code, event_name, event_phase, alarm_state, priority, timestamp`

---

## 二、云端服务（接收端）

### 0. 上传项目到云服务器

在本地终端执行（将 `user` 和 `<服务器IP>` 替换成实际值）：
```bash
scp -r /Users/Zhuanz/PycharmProjects/mindray_hl7_pipeline/ user@<服务器IP>:/opt/mindray_hl7_pipeline
```

或者用 rsync（后续更新更方便，只传有变化的文件）：
```bash
rsync -avz --exclude 'data/' --exclude 'logs/' --exclude '.venv/' /Users/Zhuanz/PycharmProjects/mindray_hl7_pipeline/ user@<服务器IP>:/opt/mindray_hl7_pipeline/
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
- `kind`: raw_hl7 / waveform_csv / events_csv
- `device_id`: 可选
- `relative_path`: 可选，保留客户端目录结构
- `file`: 上传文件

服务会将文件保存到 `DATA_DIR` 下。

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

## 三、自动上传

配置 `configs/client_config.json`：
```json
"upload": {
  "enabled": true,
  "base_url": "http://<server-ip>:10000",
  "api_key": "",
  "delete_after_upload": false,
  "min_age_seconds": 120,
  "run_in_background": true
}
```

如果 `run_in_background=true`，collector 启动时会自动拉起上传线程，无需单独运行。

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

覆盖 HL7 时间戳解析、单位映射、设备 ID 提取、MLLP 帧解码、ACK 构建、波形/事件解析，共 37 个用例。

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
| 本地有数据没上传 | `upload.enabled` 是否为 true、云端 10000 是否通 |
| 刚启动一会没上传 | 正常，文件需等待 `min_age_seconds`（默认 120s）后才上传 |
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
- **Upload endpoint:** `POST /upload` (multipart)
- **Health check:** `GET /health`
