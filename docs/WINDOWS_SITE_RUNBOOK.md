---
type: permanent
created: 2026-06-04
related_to: WINDOWS_HOSPITAL_QUICKSTART.md
---

# Windows 现场傻瓜式操作手册

这份文档给到医院现场的人使用。目标不是讲原理，而是让你按顺序操作，把 Windows 电脑和迈瑞监护仪接起来，并确认数据已经保存到本地。

如果你是现场负责人，需要先理解项目全貌、现场节奏、验收标准和故障定位逻辑，请先读 `docs\ONSITE_OPERATOR_BRIEFING.md`。

推荐主链路：

```text
迈瑞监护仪 -> 网线 -> Windows 采集电脑监听 6600 -> C:\mindray_hl7_pipeline\data 本地落盘
```

当前不要启用云端上传。`configs\client_config.json` 里应保持：

```json
"upload": {
  "enabled": false
}
```

---

## 0. 带到现场前先确认

你要带：

- 项目交付 zip：`mindray_hl7_pipeline_hospital_*.zip`
- Windows 电脑管理员权限，至少要能打开“以管理员身份运行”的 PowerShell
- 一根能连接监护仪和 Windows 电脑的网线
- Python 3.9 或更高版本安装包，建议准备 3.9 到 3.11，防止医院电脑没网
- 本文档

现场建议先问医院工程师：

- 哪台迈瑞监护仪可以测试
- 监护仪 HL7 设置菜单在哪里
- 是否允许你给 Windows 有线网卡加一个静态 IP
- 连接监护仪的网口是不是独立网口，不要改医院办公网网卡

---

## 1. 解压项目

1. 把 zip 复制到 Windows 电脑。
2. 右键 zip，选择“全部解压”。
3. 如果解压后目录名类似：

   ```text
   mindray_hl7_pipeline_hospital_20260603_122745\mindray_hl7_pipeline
   ```

   请把里面的 `mindray_hl7_pipeline` 文件夹复制到 C 盘根目录。

最终路径必须是：

```text
C:\mindray_hl7_pipeline
```

检查方法：

1. 打开“文件资源管理器”。
2. 在地址栏输入：

   ```text
   C:\mindray_hl7_pipeline
   ```

3. 里面应该能看到：

   ```text
   apps
   configs
   deploy
   docs
   README.md
   ```

如果地址栏提示找不到路径，先不要继续，说明项目没有放对位置。

---

## 2. 打开 PowerShell

后面会用两种 PowerShell：

- 普通 PowerShell：运行程序、查看文件
- 管理员 PowerShell：配置网卡 IP、防火墙

### 2.1 打开普通 PowerShell

1. 按键盘 `Win + R`。
2. 输入：

   ```text
   powershell
   ```

3. 回车。

看到蓝色或黑色命令窗口即可。

### 2.2 打开管理员 PowerShell

1. 点 Windows 开始菜单。
2. 输入：

   ```text
   powershell
   ```

3. 右键“Windows PowerShell”。
4. 选择“以管理员身份运行”。
5. 如果弹出确认，点“是”。

判断是不是管理员：窗口标题通常会有“管理员”两个字。

---

## 3. 检查 Python

在普通 PowerShell 里输入：

```powershell
python --version
```

成功时应看到类似：

```text
Python 3.10.11
```

只要是 3.9 或更高版本都可以；现场优先用 3.9、3.10、3.11 这类常见版本。

如果提示找不到 `python`：

1. 安装 Python。
2. 安装时必须勾选：

   ```text
   Add python.exe to PATH
   ```

3. 安装完关闭 PowerShell，重新打开。
4. 再执行：

   ```powershell
   python --version
   ```

如果电脑上只有 `py` 命令可用，可以临时试：

```powershell
py --version
```

但项目脚本默认使用 `python`，最好让 `python --version` 可用。

---

## 4. 安装/检查采集端

在普通 PowerShell 里执行：

```powershell
cd C:\mindray_hl7_pipeline
deploy\install.bat
```

你应该看到：

```text
[OK] Python ...
[OK] logs/ 和 data/ 目录已就绪
检查完成: ... 项通过
Double-click MindrayHL7Collector.bat on Desktop
```

说明：

- 本地 HL7 采集不需要联网安装 Python 依赖。
- 如果看到上传器、蓝牙、摄像头等 WARN，可以忽略。
- 必须关注 `HL7 监听端口 6600` 是否 OK。

如果提示 6600 被占用，先执行：

```powershell
Get-NetTCPConnection -LocalPort 6600 -State Listen
```

如果能看到占用进程，再执行：

```powershell
Get-Process -Id <OwningProcess>
```

把 `<OwningProcess>` 换成上一条命令显示的数字。找到占用程序后先关闭它。

---

## 5. 找到连接监护仪的网卡名

把网线插好：一头接 Windows 电脑有线网口，一头接迈瑞监护仪网络口。

在管理员 PowerShell 里执行：

```powershell
Get-NetAdapter | Format-Table Name, Status, InterfaceDescription
```

你会看到类似：

```text
Name       Status  InterfaceDescription
----       ------  --------------------
以太网      Up      Realtek PCIe GbE Family Controller
以太网 2    Up      USB Ethernet Adapter
WLAN       Up      Intel Wi-Fi
```

要找的是连接监护仪的有线网卡。常见名字：

- `以太网`
- `以太网 2`
- `Ethernet`
- `Ethernet 2`
- USB 网卡名

如果不确定哪一个是监护仪网口：

1. 先拔掉连接监护仪的网线。
2. 执行：

   ```powershell
   Get-NetAdapter | Format-Table Name, Status, InterfaceDescription
   ```

3. 再插上网线。
4. 再执行同一条命令。
5. 哪个网卡从 `Disconnected` / `Not Present` 变成 `Up`，哪个就是目标网卡。

下面示例都用 `以太网 2`。如果你的电脑显示别的名字，请把命令里的 `以太网 2` 替换掉。

---

## 6. 给 Windows 网卡配置静态 IP

在管理员 PowerShell 里执行。

先看当前网卡配置：

```powershell
Get-NetIPConfiguration -InterfaceAlias "以太网 2"
```

如果这里报错，说明网卡名不对，回到第 5 步重新确认。

添加采集机 IP：

```powershell
netsh interface ipv4 add address "以太网 2" 10.60.117.200 255.255.255.192
```

再次检查：

```powershell
Get-NetIPConfiguration -InterfaceAlias "以太网 2"
```

成功时应看到：

```text
IPv4Address : 10.60.117.200
```

如果提示对象已存在或 IP 已经有了，可以继续。

如果配错了网卡，删除方法是：

```powershell
netsh interface ipv4 delete address "以太网 2" 10.60.117.200
```

然后换正确网卡名重新添加。

---

## 7. 放行 Windows 防火墙 6600 端口

在管理员 PowerShell 里执行：

```powershell
netsh advfirewall firewall add rule name="Mindray-HL7-6600" dir=in action=allow protocol=TCP localport=6600
```

如果提示规则已存在，也可以继续。

检查规则：

```powershell
netsh advfirewall firewall show rule name="Mindray-HL7-6600"
```

应能看到规则信息。

---

## 8. 检查采集配置文件

打开普通 PowerShell，执行：

```powershell
cd C:\mindray_hl7_pipeline
notepad .\configs\client_config.json
```

确认这些字段：

```json
"listen_ip": "0.0.0.0",
"listen_port": 6600,
"data_dir": "data",
"compress": true,
"enable_ack": true,
"upload": {
  "enabled": false
}
```

关键点：

- `listen_port` 必须是 `6600`
- `enable_ack` 必须是 `true`
- `upload.enabled` 必须是 `false`

如果你改了文件，保存后关闭记事本。

---

## 9. 启动采集端

在普通 PowerShell 里执行：

```powershell
cd C:\mindray_hl7_pipeline
deploy\run_collector.bat
```

成功时会看到：

```text
Mindray HL7 Collector (自动重启模式)
按 Ctrl+C 停止
[日期 时间] 启动 Collector...
Listening on 0.0.0.0:6600
```

保持这个窗口不要关。

这时 Windows 已经在等监护仪连接。

---

## 10. 配置迈瑞监护仪

不同型号菜单名字可能不一样，请找类似：

```text
系统设置 / 维护 / 网络 / HL7 / 数据输出
```

需要设置：

```text
HL7 模式：客户端模式
服务器地址：10.60.117.200
端口：6600
波形发送：开启
报警发送：开启
HL7 发送：开启
```

解释：

- 监护仪是客户端。
- Windows 电脑是服务器。
- 所以监护仪里填的“服务器地址”是 Windows 电脑 IP：`10.60.117.200`。
- 端口必须和采集程序一致：`6600`。

如果监护仪要求配置自身 IP，现场已知参数是：

```text
监护仪 IP：10.60.117.196
子网掩码：255.255.255.192
网关：10.60.117.193
```

如果监护仪已有这些配置，不要随便改。

---

## 11. 判断是否连接成功

回到采集端 PowerShell 窗口。

连接成功时应看到：

```text
Connected from ('10.60.117.196', xxxx)
```

这里 `xxxx` 是随机端口，数字不同没关系。

如果一直没有 `Connected from`：

1. 监护仪服务器地址是不是 `10.60.117.200`
2. 监护仪端口是不是 `6600`
3. Windows 采集程序是否还在显示 `Listening on 0.0.0.0:6600`
4. Windows 防火墙规则是否已添加
5. 网线是否插对
6. Windows 网卡 IP 是否真的有 `10.60.117.200`

可以在管理员 PowerShell 里执行：

```powershell
Get-NetIPConfiguration -InterfaceAlias "以太网 2"
```

---

## 12. 判断是否真的保存了数据

保持采集运行 1 到 3 分钟。

再打开一个普通 PowerShell，执行：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,Length,LastWriteTime
```

成功时会看到很多文件，路径类似：

```text
C:\mindray_hl7_pipeline\data\raw_hl7\2026\06\04\10\...
C:\mindray_hl7_pipeline\data\waveform_csv\2026\06\04\10\...
C:\mindray_hl7_pipeline\data\numerics_csv\2026\06\04\10\...
```

至少应该看到：

- `raw_hl7`：原始 HL7
- `waveform_csv`：波形
- `numerics_csv`：生命体征数值，有对应数值报文时出现

`events_csv` 只有有报警/事件时才一定出现，没有也不一定是错。

---

## 13. 抽查原始 HL7 内容

在普通 PowerShell 执行：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data\raw_hl7 -Recurse -File | Where-Object { $_.Name -like '*.hl7' -or $_.Name -like '*.hl7.gz' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
  python -c "import gzip,sys; p=sys.argv[1]; opener=gzip.open if p.endswith('.gz') else open; print(opener(p, 'rt', encoding='utf-8', errors='replace').read(2000))" $_.FullName
}
```

正常应看到类似：

```text
MSH|^~\&|MINDRAY...
ORU^R01
OBX|...
```

看到 `MINDRAY`、`ORU^R01`、`OBX`，说明确实收到监护仪 HL7。

---

## 14. 抽查波形 CSV

在普通 PowerShell 执行：

```powershell
cd C:\mindray_hl7_pipeline
Get-ChildItem .\data\waveform_csv -Recurse -File | Where-Object { $_.Name -like '*.csv' -or $_.Name -like '*.csv.gz' } | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
  python -c "import gzip,sys; p=sys.argv[1]; opener=gzip.open if p.endswith('.gz') else open; print(''.join(opener(p, 'rt', encoding='utf-8', errors='replace').readlines()[:5]))" $_.FullName
}
```

正常应看到表头包含：

```text
device_id,channel_code,channel_name,start_time,end_time,sample_rate,resolution,unit,samples,samples_count,inop
```

常见波形：

- ECG：`MDC_ECG_ELEC_POTL_*`
- PLETH：`MDC_PULS_OXIM_PLETH`
- RESP：`MDC_IMPED_TTHOR`

---

## 15. 停止采集

回到采集端窗口。

按：

```text
Ctrl + C
```

如果提示是否终止批处理，输入：

```text
Y
```

然后回车。

---

## 16. 常见失败和处理

### 16.1 PowerShell 提示脚本不能运行

如果双击 `.bat` 不行，先用 PowerShell 手动执行：

```powershell
cd C:\mindray_hl7_pipeline
deploy\run_collector.bat
```

`.bat` 通常不受 PowerShell 执行策略限制。

### 16.2 `python` 找不到

现象：

```text
python 不是内部或外部命令
```

处理：

- 重新安装 Python
- 勾选 `Add python.exe to PATH`
- 关闭并重新打开 PowerShell
- 再执行 `python --version`

### 16.3 网卡名不对

现象：

```text
No MSFT_NetIPInterface objects found
```

处理：

```powershell
Get-NetAdapter | Format-Table Name, Status, InterfaceDescription
```

找到正确网卡名，把命令中的 `"以太网 2"` 替换掉。

### 16.4 端口 6600 被占用

检查：

```powershell
Get-NetTCPConnection -LocalPort 6600 -State Listen
```

如果有输出，找到进程：

```powershell
Get-Process -Id <OwningProcess>
```

关闭占用端口的程序，或重启电脑后先运行采集端。

### 16.5 一直没有 `Connected from`

按这个顺序查：

1. 采集端窗口是否显示 `Listening on 0.0.0.0:6600`
2. 监护仪 HL7 模式是否是客户端模式
3. 监护仪服务器地址是否是 `10.60.117.200`
4. 监护仪端口是否是 `6600`
5. Windows 网卡是否有 `10.60.117.200`
6. 防火墙是否已放行 6600
7. 网线是否插在正确网卡和监护仪网络口

### 16.6 连上了但没有数据文件

检查：

1. 监护仪是否开启波形发送 / HL7 发送
2. 是否有病人、导联、血氧等实际信号
3. 是否只开了报警发送但没有报警
4. 再等 1 到 3 分钟

### 16.7 有 raw_hl7 但没有 events_csv

这可能正常。`events_csv` 只有报警/事件消息出现时才会写。

### 16.8 上传没有发生

这是当前推荐状态。配置里默认：

```json
"upload": {
  "enabled": false
}
```

现场先不要打开上传。

---

## 17. 成功标准

满足下面 4 条，就算现场接入成功：

1. 采集端窗口显示：

   ```text
   Listening on 0.0.0.0:6600
   Connected from ('10.60.117.196', xxxx)
   ```

2. `C:\mindray_hl7_pipeline\data\raw_hl7` 下有 `.hl7.gz`
3. `C:\mindray_hl7_pipeline\data\waveform_csv` 下有 `.csv.gz`
4. 抽查内容能看到 `MSH|...|MINDRAY`、`ORU^R01`、`OBX`

---

## 18. 现场不要做的事

- 不要打开云端上传。
- 不要把 `data` 目录通过微信、个人网盘或未批准的公网方式发出去。
- 不要随便改医院办公网网卡 IP。
- 不要在不知道用途的情况下修改监护仪自身 IP。
- 不要删除采集出来的数据，除非医院方明确同意。
