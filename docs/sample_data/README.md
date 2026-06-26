# 示例数据包（内部参考）

本目录保留给项目内部格式参考。这里的样例可能包含设备号、病区/床位、采集时间等现场元数据，即使没有姓名/病历号，也应按敏感数据处理。

给医院方打包交付时，使用 `tools/package_for_hospital.sh`，该脚本会自动排除 `docs/sample_data/`。

如需更新样例，请在**云端**运行脚本自动抽取：

```
bash mindray_hl7_pipeline/tools/extract_samples.sh
```

生成内容位于本目录：
- `raw_hl7_sample.hl7`
- `waveform_sample.csv`
- `events_sample.csv`

说明：
- `raw_hl7_sample.hl7` 是现场报文格式样例，可能包含设备号、病区/床位和采集时间等元数据。
- `waveform_sample.csv` / `events_sample.csv` 是最小可用样例，用于格式对齐/解析验证。
- 如需更新为最新样本，请在云端运行脚本重新生成，并确认是否允许分发。

注意：不要把本目录随交付包发出，除非医院方明确允许。
