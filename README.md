# Mindray HL7 采集与落盘（Python）

本目录结构：
- **apps/client**：医院电脑上的采集端（监听 HL7/MLLP，落盘 CSV + 原始 HL7）
- **apps/server**：云端接收端（HTTP 上传文件）
- **configs**：配置文件（如 `client_config.json`）
- **docs**：部署与验收文档

完整部署文档（超详细）见：
- `mindray_hl7_pipeline/docs/DEPLOYMENT_GUIDE.md`
- 接手要点（必读）：`mindray_hl7_pipeline/docs/HANDOVER.md`

---

## 一、客户端（Windows 采集机）

### 1. 准备配置
编辑 `mindray_hl7_pipeline/configs/client_config.json`：
- `listen_port`: 6600  
- `data_dir`: `data`  
- `compress`: `true`（生成 `.gz`）  
- `device_id`: 可留空（自动从 MSH-3 解析）  

### 2. 运行采集
PowerShell 中进入 `mindray_hl7_pipeline/apps/client`：
```
python collector.py --config ..\configs\client_config.json
```

### 3. 落盘目录结构（默认）
```
data/
  raw_hl7/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM.hl7(.gz)
  waveform_csv/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM_<channel>.csv(.gz)
  events_csv/YYYY/MM/DD/HH/<device>_YYYYMMDD_HHMM_alarm.csv(.gz)
```

### 4. CSV 字段（波形）
`device_id, channel_code, channel_name, start_time, end_time, sample_rate, resolution, unit, samples, samples_count, inop`

### 5. CSV 字段（事件）
`device_id, event_code, event_name, event_phase, alarm_state, priority, timestamp`

---

## 二、云端服务（接收端）

### 1. 安装依赖
```
pip install -r mindray_hl7_pipeline/apps/server/requirements.txt
```

### 2. 启动服务
```
cd mindray_hl7_pipeline/apps/server
DATA_DIR=data uvicorn app:app --host 0.0.0.0 --port 10000
```

### 3. 上传接口
`POST /upload`（multipart/form-data）
- `kind`: raw_hl7 / waveform_csv / events_csv
- `device_id`: 可选
- `relative_path`: 可选，保留客户端目录结构
- `file`: 上传文件

服务会将文件保存到 `DATA_DIR` 下。

---

## 三、可选：自动上传脚本

安装依赖：
```
pip install -r mindray_hl7_pipeline/apps/client/requirements.txt
```

配置 `client_config.json`：
```
"upload": {
  "enabled": true,
  "base_url": "http://<server-ip>:10000",
  "delete_after_upload": false,
  "min_age_seconds": 120,
  "run_in_background": true
}
```

运行上传器（循环上传）：
```
python uploader.py --config ..\configs\client_config.json
```

如果 `run_in_background=true`，采集端启动时会自动拉起上传线程，无需单独运行 uploader。

---

## English Quick Start

- Run collector on Windows:  
  `python collector.py --config ..\\configs\\client_config.json`
- Server:  
  `uvicorn app:app --host 0.0.0.0 --port 10000`
- Upload endpoint: `POST /upload` (multipart)
