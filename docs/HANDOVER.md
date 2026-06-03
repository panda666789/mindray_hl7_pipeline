# 项目交接要点（必读版）

本页只保留“能接手并继续运行”的必要信息。

---

## 1) 一句话全链路

监护仪（HL7 客户端模式）→ 采集端监听 6600 → 本地落盘 → HTTP 上传 → 云端服务 10000 → 云端落盘

---

## 2) 关键路径（项目内）

```
mindray_hl7_pipeline/
  apps/client/collector.py      # 采集端
  apps/client/uploader.py       # 上传器（可选）
  apps/server/app.py            # 云端接收端
  configs/client_config.json    # 采集端配置
  docs/DEPLOYMENT_GUIDE.md      # 完整部署文档
```

---

## 3) 关键网络参数（现场已确认）

- 监护仪 IP：`10.60.117.196`
- 采集机 IP：`10.60.117.200/26`
- 监护仪端口：`6600`
- 云端端口：`10000`
- 监护仪模式：**HL7 客户端模式**

---

## 4) 启停与状态（必须会）

### 4.1 采集端（Windows）

启动（手工）：
```
python E:\mindray_hl7_pipeline\apps\client\collector.py --config E:\mindray_hl7_pipeline\configs\client_config.json
```

后台（计划任务）：
```
SCHTASKS /Query /TN "MindrayHL7Collector" /V /FO LIST
SCHTASKS /Run   /TN "MindrayHL7Collector"
SCHTASKS /End   /TN "MindrayHL7Collector"
```

日志：
```
E:\mindray_hl7_pipeline\logs\collector.log
```

### 4.2 云端（Linux）

systemd 服务：
```
systemctl status mindray-hl7
systemctl start  mindray-hl7
systemctl stop   mindray-hl7
```

健康检查：
```
curl http://127.0.0.1:10000/health
```

---

## 5) 数据格式要点（只需记住）

- HL7 v2.6 + MLLP  
  - 起始 `0x0b` / 结束 `0x1c 0x0d`
- 报警：`ORU^R40`  
- 波形：`ORU^R01`  
- 波形 OBX：`OBX-2=NA`，`OBX-5` 为 `v1^v2^v3...`
- 采样率/分辨率在紧随 OBX 中  

落盘 CSV：
```
waveform_csv: device_id, channel_code, start_time, end_time, sample_rate, resolution, samples, samples_count, inop
events_csv:   device_id, event_code, event_phase, alarm_state, priority, timestamp
```

---

## 6) 一键验收（最短）

云端抽查：
```
zcat /opt/mindray_hl7_pipeline/data/raw_hl7/*/*/*/*/*.hl7.gz | head -n 5
zcat /opt/mindray_hl7_pipeline/data/waveform_csv/*/*/*/*/*.csv.gz | head -n 3
```

预期看到：
- `MSH|...|MINDRAY`
- `ORU^R01` / `ORU^R40`
- `MDC_ECG_ELEC_POTL_*` / `MDC_PULS_OXIM_PLETH` / `MDC_IMPED_TTHOR`

---

## 7) 示例数据包（推荐生成）

出于隐私原因，不直接存样本。  
可在云端运行脚本自动生成样本到 `docs/sample_data/`：

```
bash mindray_hl7_pipeline/tools/extract_samples.sh
```

---

如果只看这一页，也能继续维护项目。  
需要细节请看：`docs/DEPLOYMENT_GUIDE.md`。
