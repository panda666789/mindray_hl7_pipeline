from typing import Dict, Tuple


def validate_upload_enabled(cfg: Dict) -> Tuple[bool, str]:
    upload_cfg = cfg.get("upload", {})
    if upload_cfg.get("enabled") is not True:
        return False, "upload.enabled=false，当前默认关闭上传。请先确认网络、带宽和数据合规要求后再手动开启。"
    if not upload_cfg.get("base_url"):
        return False, "配置文件中 upload.base_url 为空"
    return True, ""
