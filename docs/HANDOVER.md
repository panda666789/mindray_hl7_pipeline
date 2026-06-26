---
type: permanent
created: 2026-06-03
related_to: DEPLOYMENT_GUIDE.md
---

# 项目交接要点（必读版）

本页只保留“能接手并继续运行”的必要信息。现场负责人需要理解全貌和控场逻辑时，先看 `docs/ONSITE_OPERATOR_BRIEFING.md`；医院现场从零操作请优先看 `docs/WINDOWS_SITE_RUNBOOK.md`。

---

## 1) 一句话全链路

推荐主链路：

监护仪（HL7 客户端模式）→ Windows 采集端监听 6600 → 本地 `data/` 落盘

可选链路：

本地文件 → HTTP 上传 → 云端服务 10000 → 云端落盘

云端上传功能已经实现，但受现场带宽和文件体积限制，当前默认关闭，不建议作为试运行主流程。

原始 HL7 和 CSV 可能包含设备号、病区/床位、采集时间等敏感信息。对外打包、转发或长期留存前，需要医院方确认。

---

## 2) 关键路径（项目内）

```
mindray_hl7_pipeline/
  apps/client/collector.py      # 迈瑞 HL7 采集端，推荐试运行入口
  apps/client/hl7_parser.py     # HL7/MLLP 解析与 ACK
  apps/client/uploader.py       # 上传器，可选，不推荐当前试运行使用
  apps/server/app.py            # 云端接收端，可选
  configs/client_config.json    # 采集端配置
  deploy/install.bat            # Windows 最小采集端安装
  deploy/run_collector.bat      # Windows 采集端启动脚本
  docs/ONSITE_OPERATOR_BRIEFING.md
  docs/WINDOWS_SITE_RUNBOOK.md
  docs/WINDOWS_HOSPITAL_QUICKSTART.md
  docs/DEPLOYMENT_GUIDE.md
```

---

## 3) 关键网络参数（现场已确认）

- 监护仪 IP：`10.60.117.196`
- 采集机 IP：`10.60.117.200/26`
- 子网掩码：`255.255.255.192`
- 监护仪端口：`6600`
- 监护仪模式：**HL7 客户端模式**
- 云端端口：`10000`，仅可选上传使用

---

## 4) 启停与状态（必须会）

### 4.1 采集端（Windows）

推荐项目路径：

```
C:\mindray_hl7_pipeline
```

安装：

```
cd C:\mindray_hl7_pipeline
deploy\install.bat
```

启动：

```
cd C:\mindray_hl7_pipeline
deploy\run_collector.bat
```

手工启动等价命令：

```
python C:\mindray_hl7_pipeline\apps\client\collector.py --config C:\mindray_hl7_pipeline\configs\client_config.json
```

计划任务（只有按 `docs/DEPLOYMENT_GUIDE.md` 第 14 节手动创建后才存在；如果未创建，查询命令会提示找不到任务）：

```
SCHTASKS /Query /TN "MindrayHL7Collector" /V /FO LIST
SCHTASKS /Run   /TN "MindrayHL7Collector"
SCHTASKS /End   /TN "MindrayHL7Collector"
```

日志：

```
C:\mindray_hl7_pipeline\logs\collector.log
```

### 4.2 云端（可选）

只有手动测试上传时才需要云端服务：

```
systemctl status mindray-hl7
systemctl start  mindray-hl7
systemctl stop   mindray-hl7
curl http://127.0.0.1:10000/health
```

---

## 5) 数据格式要点（只需记住）

- HL7 v2.6 + MLLP
  - 起始 `0x0b` / 结束 `0x1c 0x0d`
- ACK 必须开启：`configs/client_config.json` 中 `enable_ack=true`
- 波形：`ORU^R01`
- 报警：`ORU^R40`
- 波形 OBX：`OBX-2=NA`，`OBX-5` 为 `v1^v2^v3...`
- 采样率/分辨率在紧随 OBX 中

落盘 CSV：

```
waveform_csv: device_id, channel_code, start_time, end_time, sample_rate, resolution, samples, samples_count, inop
numerics_csv: device_id, timestamp, code, name, value, unit
events_csv:   device_id, event_code, event_phase, alarm_state, priority, timestamp
```

---

## 6) 本地验收（最短）

Windows 采集端运行后执行：

```
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 10 FullName,Length,LastWriteTime
```

预期看到：

- `raw_hl7` 有 `.hl7.gz`
- `waveform_csv` 有 `.csv.gz`
- `numerics_csv` 在有生命体征数值报文时出现
- `events_csv` 在有报警/事件时出现
- 采集窗口出现 `Connected from ('10.60.117.196', xxxx)`

重点确认：

- 原始 HL7 中有 `MSH|...|MINDRAY`
- 有 `ORU^R01` 或 `ORU^R40`
- 波形字段中可见 `MDC_ECG_ELEC_POTL_*` / `MDC_PULS_OXIM_PLETH` / `MDC_IMPED_TTHOR`

---

## 7) 样例数据

仓库内保留 `docs/sample_data/` 作为内部格式参考，但给医院方的交付包默认不包含这些现场样例文件。

如需从云端历史数据重新抽样，需先获得医院方授权，再运行：

```
bash mindray_hl7_pipeline/tools/extract_samples.sh
```

打包时用 `tools/package_for_hospital.sh`，它会自动排除 `docs/sample_data/`。

---

如果只看这一页，也能继续维护项目。需要细节请看 `docs/DEPLOYMENT_GUIDE.md`。
