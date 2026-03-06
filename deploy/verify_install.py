"""Installation verification script for Mindray HL7 Pipeline."""

import sys
import socket


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" - {detail}"
    print(msg)
    return ok


def main() -> int:
    print("Mindray HL7 Pipeline - 安装检查\n")
    results = []

    # Python version
    v = sys.version_info
    results.append(check(
        "Python 版本",
        v.major == 3 and v.minor >= 9,
        f"{v.major}.{v.minor}.{v.micro}"
    ))

    # Core imports
    for mod, desc in [
        ("requests", "HTTP 客户端"),
        ("serial", "串口通信 (pyserial)"),
        ("cv2", "视频采集 (opencv)"),
        ("bleak", "蓝牙 BLE"),
    ]:
        try:
            __import__(mod)
            results.append(check(desc, True, mod))
        except ImportError:
            results.append(check(desc, False, f"{mod} 未安装"))

    # Optional imports (warn but don't fail)
    for mod, desc in [
        ("hid", "HID 设备 (hidapi)"),
        ("camera_list", "摄像头列表 (PyCameraList)"),
    ]:
        try:
            __import__(mod)
            check(desc, True, f"{mod} (可选)")
        except ImportError:
            check(desc, False, f"{mod} 未安装 (可选，不影响核心功能)")

    # Project modules
    sys.path.insert(0, "apps/client")
    for mod, desc in [
        ("hl7_parser", "HL7 解析模块"),
        ("log_config", "日志模块"),
        ("collector", "采集器模块"),
        ("uploader", "上传器模块"),
    ]:
        try:
            __import__(mod)
            results.append(check(desc, True))
        except Exception as e:
            results.append(check(desc, False, str(e)))

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
