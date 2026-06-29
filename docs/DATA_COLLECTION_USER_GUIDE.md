---
type: permanent
created: 2026-06-29
related_to: HANDOVER.md
---

# 数据采集软件使用说明

本文档说明本项目在 Windows 电脑上的环境配置、启动运行、采集操作、配置文件含义、输出文件结构和主要数据字段。目标是让接手使用软件的人能完成数据采集，并知道采集后每个文件是什么。

如只需要连接 Windows 电脑和迈瑞监护仪，可同时参考 `docs/WINDOWS_SITE_RUNBOOK.md`。如需要了解部署和实现细节，可参考 `docs/DEPLOYMENT_GUIDE.md`。

---

## 1. 运行入口

本项目有两个采集入口：

| 场景 | 启动脚本 | 用途 |
| --- | --- | --- |
| 只采集迈瑞监护仪 HL7 数据 | `deploy\run_collector.bat` | 监听迈瑞监护仪 6600 端口，保存原始 HL7、波形、生命体征和事件 |
| 采集摄像头、迈瑞监护仪和其他外设 | `deploy\run_physrecorder.bat` | 启动 GUI，按被试者 ID 和视频编号保存一次完整采集会话 |

如果需要同时采集摄像头和迈瑞监护仪，使用 GUI 入口 `deploy\run_physrecorder.bat`。不要同时运行 CLI 采集器和 GUI，因为两者都会监听 6600 端口。

---

## 2. Windows 环境配置

推荐项目路径：

```text
C:\mindray_hl7_pipeline
```

检查 Python：

```powershell
python --version
```

建议使用 Python 3.9 到 3.11。安装 Python 时需要勾选：

```text
Add python.exe to PATH
```

### 2.1 只运行迈瑞 HL7 CLI 采集器

CLI 采集器只依赖 Python 标准库。执行：

```powershell
cd C:\mindray_hl7_pipeline
deploy\install.bat
```

安装脚本会创建 `data`、`logs` 目录，并检查 Python、配置文件和 6600 端口。

### 2.2 运行 GUI 多设备采集软件

GUI 采集软件需要安装根目录依赖：

```powershell
cd C:\mindray_hl7_pipeline
pip install -r requirements.txt
```

如需使用 Dashboard 查看采集结果，再安装 Dashboard 依赖：

```powershell
cd C:\mindray_hl7_pipeline
pip install -r apps\dashboard\requirements.txt
```

---

## 3. 迈瑞监护仪连接配置

迈瑞监护仪使用 HL7 客户端模式，Windows 采集电脑作为服务端监听 6600 端口。

常用参数：

| 参数 | 值 |
| --- | --- |
| Windows 采集机 IP | `10.60.117.200` |
| 子网掩码 | `255.255.255.192` |
| 监护仪 IP | `10.60.117.196` |
| HL7 端口 | `6600` |

管理员 PowerShell 中配置采集机网卡：

```powershell
netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192
netsh advfirewall firewall add rule name="Mindray-HL7-6600" dir=in action=allow protocol=TCP localport=6600
```

如果现场网卡名称不是 `以太网 2`，先执行：

```powershell
Get-NetAdapter | Format-Table Name, Status, InterfaceDescription
```

然后把命令中的 `以太网 2` 替换为实际网卡名。

监护仪 HL7 设置：

```text
HL7 模式：客户端模式
服务器地址：10.60.117.200
端口：6600
波形发送：开启
报警发送：开启
HL7 发送：开启
```

---

## 4. CLI 采集器使用

启动：

```powershell
cd C:\mindray_hl7_pipeline
deploy\run_collector.bat
```

看到以下日志表示程序正在监听：

```text
Listening on 0.0.0.0:6600
```

监护仪连接后应看到：

```text
Connected from ('10.60.117.196', xxxx)
```

停止采集：在窗口中按 `Ctrl+C`。如果提示是否终止批处理，输入 `Y` 后回车。

CLI 输出目录：

```text
data\
  raw_hl7\YYYY\MM\DD\HH\*.hl7.gz
  waveform_csv\YYYY\MM\DD\HH\*.csv.gz
  numerics_csv\YYYY\MM\DD\HH\*.csv.gz
  events_csv\YYYY\MM\DD\HH\*.csv.gz
```

---

## 5. GUI 采集软件使用

启动：

```powershell
cd C:\mindray_hl7_pipeline
deploy\run_physrecorder.bat
```

采集前确认：

1. 摄像头列表扫描完成。
2. 如使用摄像头，勾选需要采集的摄像头。
3. 第一个被选中的摄像头保存为 `Camera1`，第二个保存为 `Camera2`。
4. 如果只选一路摄像头，只会生成 `Camera1`。
5. 记录每个 `CameraX` 对应的实际设备，例如 RGB 摄像头、NIR 摄像头或手机采集画面。
6. `Mindray监护仪` 区域监听端口保持 `6600`。
7. `被试者ID` 和 `视频编号` 使用脱敏编号，不要填写姓名、住院号、手机号等直接身份信息。
8. `视频编号` 每次采集应唯一；如果同一目录已存在，程序会拒绝创建，避免覆盖旧数据。
9. `录制时长(s)` 填 `0` 表示手动停止；填写正整数表示到时自动停止。

开始和停止：

1. 点击 `开始采集`。
2. 采集期间不要切换摄像头，也不要刷新摄像头列表。
3. 观察设备连接状态：摄像头、Mindray、血氧仪等需要采集的设备应处于连接状态。
4. 采集结束点击 `停止采集`。

当前不建议使用 GUI 中的 `上传数据` 按钮。`configs\client_config.json` 默认 `upload.enabled=false`，上传会被拦截。

---

## 6. GUI 输出目录和文件

GUI 模式输出目录：

```text
data\<被试者ID>\<视频编号>\
```

常见子目录：

| 子目录 | 主要文件 | 说明 |
| --- | --- | --- |
| `Camera1` | `video_seg001.avi`、`timestamps_seg001.csv`、`metadata.csv`、`missed_frames.csv` | 第一路摄像头 |
| `Camera2` | `video_seg001.avi`、`timestamps_seg001.csv`、`metadata.csv`、`missed_frames.csv` | 第二路摄像头，如有 |
| `Mindray` | `waveforms.csv`、`vitals.csv`、`events.csv` | GUI 中采集的迈瑞监护仪数据 |
| `Oximeter` | `bvp.csv`、`spo2.csv`、`hr.csv` | 血氧仪数据，如有 |
| `Respiration` | `resp.csv` | 呼吸设备数据，如有 |
| `HUB` | `sensor1.csv` 到 `sensor8.csv` | HUB 多通道数据，如有 |
| `Glasses` | `sensor1.csv`、`sensor2.csv` | 眼镜数据，如有 |

摄像头默认按 30 fps 写入视频时间轴。默认视频码率为 5 Mbps，单路摄像头约 2.2 GB/小时，两路约 4.4 GB/小时。GUI 中会显示存储空间预估。

---

## 7. 摄像头文件说明

摄像头视频文件：

```text
Camera1\video_seg001.avi
Camera2\video_seg001.avi
```

摄像头时间戳文件：

```text
Camera1\timestamps_seg001.csv
Camera2\timestamps_seg001.csv
```

如果单次采集超过分片时长，会产生：

```text
video_seg001.avi
timestamps_seg001.csv
video_seg002.avi
timestamps_seg002.csv
...
```

`timestamps_seg*.csv` 字段：

| 字段 | 含义 |
| --- | --- |
| `frame` | 当前切片内的帧号，从 0 开始 |
| `timestamp` | 摄像头帧到达程序时的本机 Unix 时间戳，兼容旧字段 |
| `capture_timestamp` | 与 `timestamp` 相同，表示实际采集到达时间 |
| `video_timestamp` | 按 `segment_start + frame / 30` 生成的稳定视频时间轴 |
| `segment` | 视频切片编号 |

使用建议：

- 做图像与波形对齐时，优先使用 `video_timestamp` 作为视频帧时间轴。
- 使用 `capture_timestamp` 检查摄像头驱动、USB 或系统调度造成的帧到达抖动。
- 每个视频分片内 `frame` 会从 0 重新开始，跨分片时需要结合 `segment`。

---

## 8. 迈瑞监护仪文件说明

GUI 模式下，迈瑞监护仪数据位于：

```text
data\<被试者ID>\<视频编号>\Mindray\
```

### 8.1 `waveforms.csv`

波形文件主要字段：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | Windows 本机收到该条波形数据的 Unix 时间戳 |
| `device_id` | 监护仪设备 ID |
| `channel_code` / `channel_name` | 波形通道，如 ECG、PLETH、RESP |
| `start_time` / `end_time` | 监护仪报文中的波形起止时间 |
| `sample_rate` | 采样率 |
| `resolution` | 原始值转换到物理值的比例 |
| `unit` | 单位 |
| `samples` | 原始采样值，使用 `^` 分隔 |
| `samples_count` | 采样点数 |
| `inop` | 异常标记 |

单个采样点可按下面方式计算：

```text
sample_time = start_time + sample_index / sample_rate
physical_value = raw_sample * resolution
```

常见通道：

| 通道 | 含义 |
| --- | --- |
| `MDC_ECG_ELEC_POTL_I` / `II` / `III` 等 | ECG 心电 |
| `MDC_PULS_OXIM_PLETH` | 血氧脉搏波 |
| `MDC_IMPED_TTHOR` | 呼吸阻抗 |

采样率以文件中的 `sample_rate` 字段为准。常见情况下 ECG 可能为 500 Hz，PLETH 可能为 60 Hz，但现场实际值应读取 CSV。

### 8.2 `vitals.csv`

生命体征数值文件字段：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | Windows 本机收到该条数据的 Unix 时间戳 |
| `device_id` | 监护仪设备 ID |
| `code` | 参数代码 |
| `name` | 参数名称，如 HR、SpO2、RR |
| `value` | 数值 |
| `unit` | 单位 |

### 8.3 `events.csv`

报警或事件文件字段：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | Windows 本机收到该条事件的 Unix 时间戳 |
| `device_id` | 监护仪设备 ID |
| `event_code` / `event_name` | 事件代码和名称 |
| `event_phase` | 事件阶段 |
| `alarm_state` | 报警状态 |
| `priority` | 报警优先级 |
| `event_timestamp` | 监护仪报文中的事件时间 |

---

## 9. 其他外设文件说明

### 9.1 血氧仪 `Oximeter`

常见文件：

| 文件 | 字段 | 说明 |
| --- | --- | --- |
| `bvp.csv` | `timestamp,bvp` | 血容量脉搏波 |
| `spo2.csv` | `timestamp,spo2` | 血氧饱和度 |
| `hr.csv` | `timestamp,hr` | 心率 |

### 9.2 呼吸设备 `Respiration`

| 文件 | 字段 | 说明 |
| --- | --- | --- |
| `resp.csv` | `timestamp,resp` | 呼吸信号 |

### 9.3 HUB、眼镜、指环类设备

这些设备通常保存为 `signals.csv`、`sensor1.csv`、`sensor2.csv` 等文件，常见字段包括：

```text
timestamp,red,ir,green,ax,ay,az,rx,ry,rz,mx,my,mz,time
```

或：

```text
timestamp,green,red,ir,ax,ay,az,gx,gy,gz,t0,t1,t2,time
```

其中 `timestamp` 为本机 Unix 时间戳，`red/ir/green` 为光学信号，`ax/ay/az` 为加速度数据，其他字段随设备类型不同而变化。

---

## 10. 配置文件说明

主要配置文件：

```text
configs\client_config.json
```

关键字段：

| 字段 | 当前默认值 | 说明 |
| --- | --- | --- |
| `listen_ip` | `0.0.0.0` | 监听所有本机网卡 |
| `listen_port` | `6600` | 迈瑞监护仪连接端口 |
| `device_id` | 空字符串 | 留空时从 HL7 报文自动解析 |
| `data_dir` | `data` | 本地数据目录 |
| `split_minutes` | `1` | CLI 模式下 CSV/HL7 文件按分钟分片 |
| `compress` | `true` | CLI 模式下输出 `.gz` 压缩文件 |
| `enable_ack` | `true` | 必须开启，否则监护仪可能发一小段后停止 |
| `write_raw_hl7` | `true` | 是否保存原始 HL7 |
| `write_waveforms` | `true` | 是否保存波形 CSV |
| `write_events` | `true` | 是否保存事件 CSV |
| `upload.enabled` | `false` | 默认关闭上传 |
| `upload.base_url` | `http://<server-ip>:10000` | 可选上传服务地址 |
| `upload.delete_after_upload` | `false` | 上传后是否删除本地文件 |

当前建议保持：

```json
"upload": {
  "enabled": false
}
```

原因是原始 HL7、波形 CSV 和视频文件可能较大，现场带宽通常不适合作为主流程上传。

---

## 11. 采后检查

查看最近生成的文件：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,Length,LastWriteTime
```

检查摄像头文件：

```powershell
Get-ChildItem .\data -Recurse -Filter "timestamps_seg*.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,Length,LastWriteTime
Get-ChildItem .\data -Recurse -Filter "video_seg*.avi" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,Length,LastWriteTime
```

检查迈瑞 GUI 数据：

```powershell
Get-ChildItem .\data -Recurse -Filter "waveforms.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,Length,LastWriteTime
Get-ChildItem .\data -Recurse -Filter "vitals.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 FullName,Length,LastWriteTime
```

抽查摄像头时间戳表头：

```powershell
Get-ChildItem .\data -Recurse -Filter "timestamps_seg*.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
  Get-Content $_.FullName -TotalCount 5
}
```

预期表头：

```text
frame,timestamp,capture_timestamp,video_timestamp,segment
```

---

## 12. Dashboard 查看数据

Dashboard 用于查看 GUI 多模态采集会话，包括摄像头帧间隔、迈瑞波形、生命体征和外设数据。

启动：

```powershell
cd C:\mindray_hl7_pipeline
$env:DATA_DIR="C:\mindray_hl7_pipeline\data"
streamlit run apps\dashboard\app.py --server.port 8501
```

浏览器打开：

```text
http://localhost:8501
```

说明：

- Dashboard 主要读取 GUI 模式的 `data\<被试者ID>\<视频编号>\...` 会话结构。
- CLI 模式下的 `data\waveform_csv\...`、`data\raw_hl7\...` 文件主要通过 PowerShell 或 Python 脚本抽查。

---

## 13. 数据交付

每次采集完成后，建议交付完整会话目录：

```text
data\<被试者ID>\<视频编号>\
```

建议同时记录采集信息：

| 字段 | 示例 |
| --- | --- |
| 被试者脱敏编号 | `S001` |
| 视频编号/会话编号 | `session_001` |
| 采集开始/结束时间 | `2026-06-29 10:00:00 - 10:05:00` |
| Camera1 对应设备 | `RGB camera` 或实际设备名 |
| Camera2 对应设备 | `NIR camera` 或实际设备名 |
| 迈瑞设备 ID | 从 GUI 状态或 `waveforms.csv` 中读取 |
| 主要通道 | ECG、PLETH、RESP、HR、SpO2 等 |
| 异常说明 | 掉线、摄像头遮挡、导联脱落、时间偏移等 |

数据可能包含设备号、采集时间、床旁环境和生理信号。复制、转移和长期保存前，应确认医院或项目的数据安全要求。

