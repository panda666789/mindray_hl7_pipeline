"""Installation verification script for Mindray HL7 Pipeline."""

import json
import sys
import socket
from pathlib import Path


def check(label: str, ok: bool, detail: str = "", required: bool = True) -> bool:
    status = "OK" if ok else ("FAIL" if required else "WARN")
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" - {detail}"
    print(msg)
    return ok


def main() -> int:
    print("Mindray HL7 Pipeline - 安装检查\n")
    results = []
    project_dir = Path(__file__).resolve().parents[1]

    # Python version
    v = sys.version_info
    results.append(check(
        "Python 版本",
        v.major == 3 and v.minor >= 9,
        f"{v.major}.{v.minor}.{v.micro}"
    ))

    # Optional uploader import. It is not required for local monitor-only
    # collection because upload.enabled defaults to false.
    for mod, desc in [
        ("requests", "HTTP 客户端/上传器依赖"),
    ]:
        try:
            __import__(mod)
            check(desc, True, f"{mod} (可选)", required=False)
        except ImportError:
            check(desc, False, f"{mod} 未安装 (可选，不影响本地采集)", required=False)

    # Optional GUI / multimodal imports. They are not required for the
    # monitor-only collector that hospitals usually test first.
    for mod, desc in [
        ("serial", "串口通信 (pyserial)"),
        ("cv2", "视频采集 (opencv)"),
        ("bleak", "蓝牙 BLE"),
        ("hid", "HID 设备 (hidapi)"),
        ("camera_list", "摄像头列表 (PyCameraList)"),
    ]:
        try:
            __import__(mod)
            check(desc, True, f"{mod} (可选)", required=False)
        except ImportError:
            check(desc, False, f"{mod} 未安装 (可选，不影响核心功能)", required=False)

    # Project modules
    sys.path.insert(0, str(project_dir / "apps" / "client"))
    for mod, desc in [
        ("hl7_parser", "HL7 解析模块"),
        ("log_config", "日志模块"),
        ("collector", "采集器模块"),
    ]:
        try:
            __import__(mod)
            results.append(check(desc, True))
        except Exception as e:
            results.append(check(desc, False, str(e)))

    try:
        __import__("uploader")
        check("上传器模块", True, "可选", required=False)
    except Exception as e:
        check("上传器模块", False, f"{e} (可选，不影响本地采集)", required=False)

    # Config safety checks for hospital handoff.
    config_path = project_dir / "configs" / "client_config.json"
    try:
        with config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        results.append(check("客户端配置文件", True, str(config_path)))
        results.append(check("HL7 监听端口配置", cfg.get("listen_port") == 6600, str(cfg.get("listen_port"))))
        results.append(check("ACK 配置", cfg.get("enable_ack") is True, str(cfg.get("enable_ack"))))
        upload_enabled = cfg.get("upload", {}).get("enabled")
        results.append(check("默认关闭上传", upload_enabled is False, str(upload_enabled)))
    except Exception as e:
        results.append(check("客户端配置文件", False, str(e)))

    # Port availability
    for port, desc in [(6600, "HL7 监听端口 6600")]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("0.0.0.0", port))
            s.close()
            results.append(check(desc, True, "可用"))
        except OSError:
            results.append(check(desc, False, "被占用"))

    # Summary
    failed = sum(1 for r in results if not r)
    print(f"\n检查完成: {len(results) - failed}/{len(results)} 项通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
