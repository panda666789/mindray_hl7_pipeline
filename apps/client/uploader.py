import argparse
import json
import os
import time
from typing import Callable, Dict, Iterable, Tuple

import requests


def load_config(path: str) -> Dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_files(base_dir: str) -> Iterable[Tuple[str, str]]:
    for root, _, files in os.walk(base_dir):
        for name in files:
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, base_dir)
            yield path, rel


def upload_one(base_url: str, path: str, rel: str, kind: str, device_id: str, timeout: int) -> bool:
    url = base_url.rstrip("/") + "/upload"
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f)}
        data = {
            "kind": kind,
            "device_id": device_id,
            "relative_path": rel.replace("\\", "/"),
        }
        resp = requests.post(url, data=data, files=files, timeout=timeout)
    return resp.status_code == 200


def run_uploader(cfg: Dict, once: bool = False, log_fn: Callable[[str], None] = print) -> None:
    upload = cfg.get("upload", {})
    enabled = upload.get("enabled", False)
    base_url = upload.get("base_url", "")
    delete_after = upload.get("delete_after_upload", False)
    timeout = int(upload.get("timeout_seconds", 15))
    retry = int(upload.get("retry_seconds", 30))
    min_age = int(upload.get("min_age_seconds", 120))
    data_dir = cfg.get("data_dir", "data")
    device_id = cfg.get("device_id", "")

    if not enabled:
        log_fn("upload.enabled = false, exit")
        return
    if not base_url:
        log_fn("upload.base_url missing, exit")
        return

    while True:
        now = time.time()
        for path, rel in iter_files(data_dir):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if now - mtime < min_age:
                continue
            kind = rel.split(os.sep, 1)[0]
            ok = upload_one(base_url, path, rel, kind, device_id, timeout)
            if ok:
                log_fn(f"uploaded {rel}")
            if ok and delete_after:
                try:
                    os.remove(path)
                except OSError:
                    pass
        if once:
            break
        time.sleep(retry)


def main():
    parser = argparse.ArgumentParser(description="Upload Mindray HL7 files to server")
    parser.add_argument("--config", default="config.json", help="client config json")
    parser.add_argument("--once", action="store_true", help="run once and exit")
    args = parser.parse_args()

    cfg = load_config(args.config)
    run_uploader(cfg, once=args.once)


if __name__ == "__main__":
    main()
