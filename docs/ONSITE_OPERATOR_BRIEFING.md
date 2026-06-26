---
type: permanent
created: 2026-06-25
related_to: WINDOWS_SITE_RUNBOOK.md
---

# 现场负责人全貌与细节手册

这份文档是给你在 2026-06-26 早上 8 点去医院现场前读的。它不是只让你照着敲命令，而是帮你先理解整个项目、现场链路、每一步为什么要做、做到什么程度算成功、卡住时应该从哪里排查。

如果你今天要按“无感体征采集流程、长庚婴儿采集软件更新、迈瑞 U 盘导出和 CMS Viewer 查看”这些任务推进，请先看 `docs\ONSITE_TRIP_TASK_BRIEFING_20260626.md`，再回到本文档看 Windows + 迈瑞 HL7 接入细节。

现场推荐主链路只有一条：

```text
迈瑞监护仪
  -> TCP/MLLP/HL7
  -> Windows 采集电脑监听 6600
  -> 回 ACK 给监护仪
  -> 本地写入 C:\mindray_hl7_pipeline\data
```

当前不要把云端上传作为现场主流程。代码里已经实现了上传器和云端接收端，但波形和原始 HL7 文件体积较大，医院现场带宽通常有限，持续上传会非常慢，实际试运行价值不高。现场验收以 Windows 本地落盘为准。

---

## 1. 你现场的目标

现场目标不是把所有扩展能力都跑起来，而是完成一个可验证的最小闭环：

1. Windows 电脑能运行本项目采集端。
2. Windows 有线网卡和迈瑞监护仪在同一网段。
3. 采集端在 Windows 上监听 TCP 6600。
4. 迈瑞监护仪以 HL7 客户端模式主动连接 Windows。
5. 采集端窗口出现 `Connected from (...)`。
6. 本地 `data` 目录持续生成原始 HL7 和 CSV 文件。
7. 抽查文件内容能看到 `MSH`、`ORU^R01`、`OBX`，以及波形或生命体征字段。

你可以把成功标准说成一句话：

```text
监护仪已经连上 Windows 采集端，Windows 本地持续保存原始 HL7 和波形 CSV；如果监护仪发送生命体征数值，也会保存生命体征 CSV。
```

---

## 2. 现场不要做什么

为了避免现场被旁支拖住，先明确不做的事：

- 不启用云端上传作为主验收。
- 不要求医院开放公网端口。
- 不要求把采集电脑接入公网服务器。
- 不随便改医院办公网网卡。
- 不把采集到的数据发到微信、个人网盘或未批准的公网服务。
- 不删除项目里的内部示例文件。医院交付包会在打包时排除 `docs/sample_data`，不是在仓库里删除它。

如果医院方问“能不能传云”，回答口径：

```text
系统有上传模块，但当前试运行建议先关闭上传。波形和原始 HL7 文件较大，现场带宽不一定支持稳定上传；本次先验证本地采集可靠性。后续如需上传，需要医院确认网络、合规、带宽和安全边界后再单独启用。
```

---

## 3. 项目组件全貌

项目根目录建议放在 Windows：

```text
C:\mindray_hl7_pipeline
```

关键目录和文件：

```text
mindray_hl7_pipeline
├── apps
│   ├── client
│   │   ├── collector.py          # 现场主程序，监听 HL7 并写本地文件
│   │   ├── hl7_parser.py         # MLLP 解包、HL7 解析、ACK 生成
│   │   ├── uploader.py           # 可选上传器，当前默认关闭
│   │   └── PhysRecorder.py       # 可选 GUI，多设备采集，不是本次主流程
│   └── server
│       └── app.py                # 可选云端接收端，当前不作为主流程
├── configs
│   └── client_config.json        # Windows 采集端配置
├── deploy
│   ├── install.bat               # Windows 安装/检查脚本
│   ├── run_collector.bat         # Windows 启动采集脚本
│   └── verify_install.py         # 安装检查脚本
├── docs
│   ├── ONSITE_OPERATOR_BRIEFING.md
│   ├── WINDOWS_SITE_RUNBOOK.md
│   ├── WINDOWS_HOSPITAL_QUICKSTART.md
│   ├── DEPLOYMENT_GUIDE.md
│   └── HANDOVER.md
├── tools
│   └── package_for_hospital.sh   # 打包给医院用，自动排除运行产物和示例数据
├── data                          # 运行后自动创建，采集数据在这里
└── logs                          # 运行后自动创建，日志在这里
```

本次现场最重要的文件只有这几个：

| 文件 | 你需要知道什么 |
| --- | --- |
| `configs\client_config.json` | 监听端口、ACK、是否上传都在这里 |
| `deploy\install.bat` | 第一次在 Windows 上跑，用来检查环境并创建目录 |
| `deploy\run_collector.bat` | 真正启动采集端 |
| `apps\client\collector.py` | 监听端口、收 HL7、写文件、回 ACK |
| `apps\client\hl7_parser.py` | 解析 MLLP/HL7 报文 |
| `docs\WINDOWS_SITE_RUNBOOK.md` | 现场逐步照做版 |

---

## 4. 数据流细节

### 4.1 网络方向

这里最容易搞反。

正确方向：

```text
迈瑞监护仪是客户端
Windows 采集电脑是服务端
监护仪主动连接 Windows 的 6600 端口
```

所以监护仪里要填的是 Windows 采集电脑的 IP：

```text
服务器地址：10.60.117.200
端口：6600
```

Windows 采集端配置里监听：

```json
"listen_ip": "0.0.0.0",
"listen_port": 6600
```

`0.0.0.0` 的意思是 Windows 在本机所有网卡上监听，不是让监护仪填 `0.0.0.0`。

### 4.2 HL7 和 MLLP

迈瑞发过来的不是普通文本流，而是 HL7 v2.x 报文套在 MLLP 帧里。

MLLP 帧边界：

```text
起始字节：0x0b
结束字节：0x1c 0x0d
```

采集端做的事情：

1. 从 TCP 连接里接收 bytes。
2. 按 MLLP 边界拆成完整 HL7 报文。
3. 解析 `MSH`、`OBR`、`OBX` 等段。
4. 根据报文类型写不同文件。
5. 给监护仪回 ACK。

### 4.3 ACK 为什么重要

配置里必须保持：

```json
"enable_ack": true
```

因为监护仪发送 HL7 后通常期待收到 ACK。如果不回 ACK，可能出现：

- 刚开始能连上，但发一小段后停止。
- 监护仪认为对端未正确接收。
- 数据流不稳定。

采集端回的是 HL7 ACK，核心是：

```text
MSA|AA|<原消息ID>
```

你不需要手写 ACK，只要确认配置里 `enable_ack` 是 `true`。

### 4.4 报文类型和落盘类型

采集端主要处理：

| 报文类型 | 含义 | 落盘 |
| --- | --- | --- |
| `ORU^R01` | 波形和生命体征数值 | `waveform_csv`、`numerics_csv` |
| `ORU^R40` | 报警/事件 | `events_csv` |
| 所有合法 HL7 | 原始报文 | `raw_hl7` |

现场验收时，`events_csv` 不一定马上出现，因为它依赖报警/事件。没有报警时只看到 `raw_hl7`、`waveform_csv`、`numerics_csv` 也可以。

---

## 5. 关键配置解释

打开：

```powershell
notepad C:\mindray_hl7_pipeline\configs\client_config.json
```

推荐配置：

```json
{
  "listen_ip": "0.0.0.0",
  "listen_port": 6600,
  "device_id": "",
  "data_dir": "data",
  "split_minutes": 1,
  "compress": true,
  "enable_ack": true,
  "write_raw_hl7": true,
  "write_events": true,
  "write_waveforms": true,
  "ack_app": "RECV",
  "ack_facility": "RECV",
  "upload": {
    "enabled": false
  }
}
```

字段含义：

| 字段 | 现场建议 | 说明 |
| --- | --- | --- |
| `listen_ip` | `0.0.0.0` | 监听所有本机网卡 |
| `listen_port` | `6600` | 必须和监护仪里填的端口一致 |
| `device_id` | 空字符串 | 空时自动从 HL7 `MSH-3` 提取设备 ID |
| `data_dir` | `data` | 数据写到项目目录下的 `data` |
| `split_minutes` | `1` | 每 1 分钟分桶写文件 |
| `compress` | `true` | 输出 `.gz`，节省空间 |
| `enable_ack` | `true` | 必须开，保证监护仪持续发送 |
| `write_raw_hl7` | `true` | 保存原始 HL7，便于追溯 |
| `write_events` | `true` | 保存报警/事件 |
| `write_waveforms` | `true` | 保存波形和数值 |
| `upload.enabled` | `false` | 当前必须保持关闭 |

---

## 6. 网络参数全貌

现场当前使用的参数：

```text
Windows 采集机 IP：10.60.117.200
监护仪 IP：10.60.117.196
子网掩码：255.255.255.192
网关：10.60.117.193
采集端口：6600
```

这些地址在同一个 `/26` 网段内。你可以粗略理解为：

```text
10.60.117.193 到 10.60.117.254 互相可达
```

现场重点：

- Windows 连接监护仪的有线网卡要有 `10.60.117.200`。
- 监护仪要知道服务器是 `10.60.117.200:6600`。
- Windows 防火墙要允许 TCP 入站 `6600`。
- 不要把医院办公网网卡随便改成这个 IP。

---

## 7. 2026-06-26 早上 8 点现场推进节奏

你可以按这个节奏控场。

### 8:00 到 8:10，先确认现场条件

问医院工程师这几个问题：

1. 本次用哪台迈瑞监护仪测试？
2. 监护仪 HL7 设置菜单在哪里？
3. Windows 电脑有没有管理员权限？
4. 连接监护仪的是哪一个有线网口？
5. 是否允许给这个有线网卡加静态 IP `10.60.117.200`？
6. 这台电脑是否能安装或已经安装 Python 3.9 或更高版本？
7. 采集数据是否只能留在本机，能否拷贝样例需要谁授权？

现场口径：

```text
我们本次先做本地采集闭环，不启用云端上传，不改医院办公网，只配置连接监护仪的独立有线网卡。
```

### 8:10 到 8:20，放置项目和检查 Python

把交付 zip 解压，最终路径固定成：

```text
C:\mindray_hl7_pipeline
```

普通 PowerShell：

```powershell
python --version
```

接受 Python 3.9 或更高版本；现场优先用这些常见版本：

```text
Python 3.9.x
Python 3.10.x
Python 3.11.x
```

如果没有 Python，就安装离线包。安装时必须勾选：

```text
Add python.exe to PATH
```

安装后关闭 PowerShell，重新打开，再查一次：

```powershell
python --version
```

### 8:20 到 8:30，安装检查

普通 PowerShell：

```powershell
cd C:\mindray_hl7_pipeline
deploy\install.bat
```

看到以下几类结果就可以继续：

```text
[OK] Python ...
[OK] logs/ 和 data/ 目录已就绪
[OK] HL7 监听端口 6600 - 可用
[OK] 默认关闭上传 - False
```

如果有这些 WARN，可以忽略：

```text
requests 未安装
serial 未安装
cv2 未安装
bleak 未安装
hid 未安装
camera_list 未安装
```

原因：本次主流程只跑本地 HL7 CLI 采集，不跑上传器、不跑 GUI 多设备。

### 8:30 到 8:45，配置 Windows 网卡和防火墙

管理员 PowerShell：

```powershell
Get-NetAdapter | Format-Table Name, Status, LinkSpeed, InterfaceDescription
```

找出连接监护仪的有线网卡。常见名称：

```text
以太网
以太网 2
Ethernet
Ethernet 2
```

如果不确定，拔插网线，看哪个网卡状态变化。

假设网卡叫 `以太网 2`，添加 IP：

```powershell
netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192
```

检查：

```powershell
Get-NetIPConfiguration -InterfaceAlias "以太网 2"
```

要看到：

```text
IPv4Address : 10.60.117.200
```

放行防火墙：

```powershell
netsh advfirewall firewall add rule name="Mindray-HL7-6600" dir=in action=allow protocol=TCP localport=6600
```

检查规则：

```powershell
netsh advfirewall firewall show rule name="Mindray-HL7-6600"
```

### 8:45 到 8:50，启动采集端

普通 PowerShell：

```powershell
cd C:\mindray_hl7_pipeline
deploy\run_collector.bat
```

成功启动时看到：

```text
Mindray HL7 Collector (自动重启模式)
Listening on 0.0.0.0:6600
```

这个窗口不要关。它就是现场主程序。

如果想本机自测 6600 是否真的在监听，另开一个普通 PowerShell：

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 6600
```

成功时：

```text
TcpTestSucceeded : True
```

### 8:50 到 9:00，配置监护仪

请医院工程师进入迈瑞监护仪菜单。不同型号名字可能不同，找类似：

```text
系统设置
维护
网络
HL7
数据输出
第三方接口
```

设置方向：

```text
HL7 模式：客户端模式
服务器地址：10.60.117.200
服务器端口：6600
HL7 发送：开启
波形发送：开启
报警发送：开启
```

如果监护仪要求自身网络参数，优先确认现有值，不要随便改。现场已知值是：

```text
监护仪 IP：10.60.117.196
子网掩码：255.255.255.192
网关：10.60.117.193
```

### 9:00 到 9:15，确认连接和数据

采集端窗口里看到：

```text
Connected from ('10.60.117.196', xxxx)
```

`xxxx` 是随机端口，不用管。

然后保持运行 1 到 3 分钟。

另开普通 PowerShell：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,Length,LastWriteTime
```

理想结果能看到：

```text
data\raw_hl7\...
data\waveform_csv\...
data\numerics_csv\...  # 有生命体征数值报文时出现
```

有报警或事件时还会看到：

```text
data\events_csv\...
```

抽查原始 HL7：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data\raw_hl7 -Recurse -File | Where-Object { $_.Name -like '*.hl7' -or $_.Name -like '*.hl7.gz' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
  python -c "import gzip,sys; p=sys.argv[1]; opener=gzip.open if p.endswith('.gz') else open; print(opener(p, 'rt', encoding='utf-8', errors='replace').read(2000))" $_.FullName
}
```

正常应该看到类似关键词：

```text
MSH|^~\&
MINDRAY
ORU^R01
OBX
```

抽查波形 CSV：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data\waveform_csv -Recurse -File | Where-Object { $_.Name -like '*.csv' -or $_.Name -like '*.csv.gz' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
  python -c "import gzip,sys; p=sys.argv[1]; opener=gzip.open if p.endswith('.gz') else open; print(''.join(opener(p, 'rt', encoding='utf-8', errors='replace').readlines()[:5]))" $_.FullName
}
```

正常表头：

```text
device_id,channel_code,channel_name,start_time,end_time,sample_rate,resolution,unit,samples,samples_count,inop
```

### 9:15 以后，稳定性观察

建议至少连续跑 5 到 10 分钟。

观察：

- 采集端窗口没有反复报错。
- `data` 下文件持续更新。
- 监护仪没有停止发送。
- `logs\collector.log` 里没有持续异常。

查看日志：

```powershell
cd C:\mindray_hl7_pipeline
Get-Content .\logs\collector.log -Tail 80
```

---

## 8. 成功验收清单

现场可以按这个清单逐项打钩。

```text
[ ] 项目位于 C:\mindray_hl7_pipeline
[ ] python --version 显示 3.9 或更高版本
[ ] deploy\install.bat 核心检查通过
[ ] configs\client_config.json 中 upload.enabled=false
[ ] configs\client_config.json 中 enable_ack=true
[ ] Windows 目标有线网卡有 10.60.117.200
[ ] Windows 防火墙已放行 TCP 6600
[ ] 采集端显示 Listening on 0.0.0.0:6600
[ ] 监护仪 HL7 客户端模式，服务器地址 10.60.117.200，端口 6600
[ ] 采集端显示 Connected from
[ ] data\raw_hl7 有 .hl7.gz 文件
[ ] data\waveform_csv 有 .csv.gz 文件
[ ] 如监护仪发送生命体征数值，data\numerics_csv 有 .csv 或 .csv.gz 文件
[ ] 抽查原始 HL7 能看到 MSH / ORU / OBX
[ ] 连续运行 5 到 10 分钟，文件持续增长
```

验收截图建议：

- `python --version`
- `deploy\install.bat` 检查结果
- `Get-NetIPConfiguration` 显示 `10.60.117.200`
- 采集窗口 `Listening` 和 `Connected from`
- `Get-ChildItem .\data -Recurse` 显示文件
- 原始 HL7 抽查结果

---

## 9. 故障定位总原则

现场排查不要同时改很多东西。按层检查：

```text
第 1 层：项目路径和 Python
第 2 层：采集程序是否启动并监听 6600
第 3 层：Windows 网卡 IP 和防火墙
第 4 层：监护仪 HL7 客户端设置
第 5 层：是否收到连接
第 6 层：是否写出文件
第 7 层：文件内容是否符合预期
```

每次只改一处，改完重新验证。

---

## 10. 常见问题处理

### 10.1 `python` 找不到

现象：

```text
python 不是内部或外部命令
```

处理：

1. 安装 Python 3.9 或更高版本，建议 3.9 到 3.11。
2. 安装时勾选 `Add python.exe to PATH`。
3. 关闭所有 PowerShell。
4. 重新打开 PowerShell。
5. 再运行：

```powershell
python --version
```

### 10.2 `deploy\install.bat` 报可选依赖 WARN

如果 WARN 是这些，可以忽略：

```text
requests
serial
cv2
bleak
hid
camera_list
```

它们分别用于上传、串口、视频、蓝牙、HID、摄像头，不影响本地 HL7 采集。

### 10.3 端口 6600 被占用

检查：

```powershell
Get-NetTCPConnection -LocalPort 6600 -State Listen
```

如果有输出，查看进程：

```powershell
Get-Process -Id <OwningProcess>
```

把 `<OwningProcess>` 换成上一条命令显示的数字。

处理方式：

- 关闭占用程序。
- 或重启电脑后先启动本采集端。

不要随便把端口改成别的。除非监护仪端口也一起改，否则两边不一致会连不上。

### 10.4 网卡名不确定

管理员 PowerShell：

```powershell
Get-NetAdapter | Format-Table Name, Status, LinkSpeed, InterfaceDescription
```

拔掉监护仪网线，执行一次。

插上监护仪网线，再执行一次。

哪个网卡状态变化，哪个就是目标网卡。

### 10.5 IP 加错网卡

如果把 `10.60.117.200` 加到了错误网卡，先删除：

```powershell
netsh interface ipv4 delete address "错误网卡名" 10.60.117.200
```

再给正确网卡添加：

```powershell
netsh interface ipv4 add address "正确网卡名" 10.60.117.200 255.255.255.192
```

### 10.6 采集端启动了，但监护仪连不上

先确认采集端窗口有：

```text
Listening on 0.0.0.0:6600
```

再按顺序查：

1. Windows 目标网卡是否有 `10.60.117.200`。
2. 监护仪服务器地址是否填 `10.60.117.200`。
3. 监护仪服务器端口是否填 `6600`。
4. 监护仪是不是 HL7 客户端模式。
5. 防火墙是否放行 TCP 6600。
6. 网线是否插对口。
7. 是否有医院网络安全策略拦截。

Windows 本机检查监听：

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 6600
```

查看是否已有连接：

```powershell
Get-NetTCPConnection -LocalPort 6600
```

如果已经连上，可能看到：

```text
LocalAddress   LocalPort RemoteAddress    RemotePort State
10.60.117.200  6600      10.60.117.196    12345      Established
```

### 10.7 出现 `Connected from`，但没有数据文件

先等 1 到 3 分钟，再查：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,Length,LastWriteTime
```

如果还是没有：

1. 监护仪是否开启 HL7 发送。
2. 是否开启波形发送。
3. 是否有实际病人或模拟信号。
4. 是否只开了报警发送但当前没有报警。
5. `configs\client_config.json` 中 `write_raw_hl7`、`write_waveforms` 是否为 `true`。

### 10.8 有 raw_hl7，但没有 waveform_csv

说明已经收到原始报文，但报文里可能不是波形 `ORU^R01`，或者波形发送没开。

抽查原始 HL7：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data\raw_hl7 -Recurse -File | Where-Object { $_.Name -like '*.hl7' -or $_.Name -like '*.hl7.gz' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
  python -c "import gzip,sys; p=sys.argv[1]; opener=gzip.open if p.endswith('.gz') else open; txt=opener(p, 'rt', encoding='utf-8', errors='replace').read(4000); print(txt)" $_.FullName
}
```

看里面有没有：

```text
ORU^R01
OBX
```

如果只有其他类型，请回监护仪菜单确认波形发送。

### 10.9 有 waveform_csv，但没有 events_csv

这通常不是问题。`events_csv` 依赖报警/事件。没有报警时可以没有。

### 10.10 发一会儿就断

重点检查：

```json
"enable_ack": true
```

然后看日志：

```powershell
cd C:\mindray_hl7_pipeline
Get-Content .\logs\collector.log -Tail 120
```

如果日志反复出现连接断开再连接，要记录发生时间、监护仪状态、网络连接方式，后续再分析。

### 10.11 上传没有发生

这是正确状态。

配置应为：

```json
"upload": {
  "enabled": false
}
```

如果医院方临时要求上传，不建议现场直接开启。需要先确认：

- 上传目的服务器。
- 网络是否允许。
- 数据是否允许离开医院内网。
- 是否必须 HTTPS/VPN。
- API Key 如何保管。
- 文件体积和带宽是否能承受。

---

## 11. 现场要会解释的几句话

### 给医院技术人员

```text
这套程序现在先作为本地采集端使用。监护仪主动连 Windows 的 6600 端口，Windows 收到 HL7 后回 ACK，并把原始 HL7、波形 CSV、生命体征 CSV 保存到本机 data 目录。
```

### 给担心网络的人

```text
本次不需要公网，也不需要云服务器。只需要监护仪和 Windows 采集网卡在同一个小网段内互通。
```

### 给担心数据的人

```text
默认不上传云端。采集数据只落在 Windows 本机 C:\mindray_hl7_pipeline\data。是否拷贝、留存或带出，需要按医院内部数据安全要求确认。
```

### 给问为什么要 ACK 的人

```text
监护仪发送 HL7 后需要对端确认收到。采集端回 ACK 是为了让监护仪持续稳定发送，不然可能发一段就停。
```

---

## 12. 交付包和打包逻辑

打包给医院时，用 Mac 或开发机在项目根目录执行：

```bash
tools/package_for_hospital.sh
```

输出在：

```text
dist/mindray_hl7_pipeline_hospital_YYYYMMDD_HHMMSS.zip
```

打包脚本会自动排除：

```text
.git
.venv
data
logs
dist
__pycache__
.pytest_cache
docs/sample_data
.DS_Store
*.pyc
```

注意：

- `docs/sample_data` 在仓库里保留，供内部理解格式。
- 医院交付包默认不带 `docs/sample_data`。
- 现场采集产生的 `data` 和 `logs` 也不会被打包进交付包。

---

## 13. 现场完成后要记录什么

建议你现场最后记录一份信息，方便后续远程支持。

```text
现场日期：
医院/科室：
Windows 电脑型号：
Windows 版本：
Python 版本：
项目目录：C:\mindray_hl7_pipeline
监护仪品牌/型号：
监护仪 IP：
Windows 采集网卡名：
Windows 采集网卡 IP：
HL7 端口：
是否看到 Connected from：
raw_hl7 最新文件路径：
waveform_csv 最新文件路径：
numerics_csv 最新文件路径：
events_csv 是否出现：
连续运行时长：
是否出现断连：
医院方联系人：
遗留问题：
```

如果医院允许截图，建议保存这些截图：

1. 采集端 `Connected from`。
2. `Get-NetIPConfiguration`。
3. `Get-ChildItem .\data -Recurse`。
4. 原始 HL7 抽查内容。
5. 波形 CSV 表头。

---

## 14. 你明早最短操作路线

如果现场时间很紧，就按这个最短路线：

```powershell
# 1. 放好项目
cd C:\mindray_hl7_pipeline

# 2. 查 Python
python --version

# 3. 安装检查
deploy\install.bat

# 4. 管理员 PowerShell 查网卡
Get-NetAdapter | Format-Table Name, Status, LinkSpeed, InterfaceDescription

# 5. 管理员 PowerShell 给目标网卡加 IP
netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192

# 6. 管理员 PowerShell 放行 6600
netsh advfirewall firewall add rule name="Mindray-HL7-6600" dir=in action=allow protocol=TCP localport=6600

# 7. 普通 PowerShell 启动采集
cd C:\mindray_hl7_pipeline
deploy\run_collector.bat

# 8. 监护仪设置
# HL7 客户端模式，服务器 10.60.117.200，端口 6600

# 9. 另开 PowerShell 验证数据
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,Length,LastWriteTime
```

最短成功判断：

```text
Listening on 0.0.0.0:6600
Connected from ('10.60.117.196', xxxx)
data\raw_hl7 有文件
data\waveform_csv 有文件
data\numerics_csv 有文件（有生命体征数值报文时）
```

---

## 15. 现场文档阅读顺序

你自己先读：

1. `docs\ONSITE_TRIP_TASK_BRIEFING_20260626.md`，按今天出差任务控场。
2. `docs\ONSITE_OPERATOR_BRIEFING.md`，理解 Windows + 迈瑞接入全貌和控场逻辑。
3. `docs\WINDOWS_SITE_RUNBOOK.md`，按步骤执行。

给医院技术人员看：

1. `docs\WINDOWS_HOSPITAL_QUICKSTART.md`，短版快速上手。
2. `docs\WINDOWS_SITE_RUNBOOK.md`，需要从零照做时看。

后续维护人员看：

1. `docs\HANDOVER.md`。
2. `docs\DEPLOYMENT_GUIDE.md`。
