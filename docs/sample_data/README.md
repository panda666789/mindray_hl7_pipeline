# 示例数据包（生成说明）

出于隐私/合规考虑，本仓库不直接存真实监护仪数据。  
需要样例时，请在**云端**运行脚本自动抽取：

```
bash mindray_hl7_pipeline/tools/extract_samples.sh
```

生成内容位于本目录：
- `raw_hl7_sample.hl7`
- `waveform_sample.csv`
- `events_sample.csv`

说明：
- `raw_hl7_sample.hl7` 已提供一份真实报文样例（来自现场抓包，已脱敏到设备级别）。
- `waveform_sample.csv` / `events_sample.csv` 已提供最小可用样例（用于格式对齐/解析验证）。
- 如需更新为最新样本，请在云端运行脚本重新生成。

注意：这些样本仍可能包含真实设备信息，请谨慎传播。
