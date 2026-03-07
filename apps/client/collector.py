import argparse
import csv
import datetime as dt
import gzip
import json
import os
import queue
import re
import socket
import threading
import time
from typing import Dict, List, Optional, Tuple

from hl7_parser import (
    MLLP_START, MLLP_END, UNIT_MAP,
    parse_hl7_timestamp, safe_unit, extract_device_id,
    parse_obs_id, decode_mllp_frames, build_ack,
    process_oru_r01, process_oru_r40,
)
from log_config import setup_logger

logger = setup_logger("collector")

DEFAULT_CONFIG = {
    "listen_ip": "0.0.0.0",
    "listen_port": 6600,
    "device_id": "",
    "data_dir": "data",
    "split_minutes": 1,
    "compress": True,
    "enable_ack": True,
    "write_raw_hl7": True,
    "write_events": True,
    "write_waveforms": True,
    "ack_app": "RECV",
    "ack_facility": "RECV",
    "upload": {
        "enabled": False,
        "base_url": "http://127.0.0.1:10000",
        "delete_after_upload": False,
        "timeout_seconds": 15,
        "retry_seconds": 30
    }
}

def log(msg: str) -> None:
    logger.info(msg)


def load_config(path: str) -> Dict:
    if not os.path.exists(path):
        return DEFAULT_CONFIG.copy()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(data)
    if "upload" in data:
        merged = DEFAULT_CONFIG["upload"].copy()
        merged.update(data["upload"])
        cfg["upload"] = merged
    return cfg


def bucket_time(ts: dt.datetime, minutes: int) -> dt.datetime:
    minute = ts.minute - (ts.minute % minutes)
    return ts.replace(minute=minute, second=0, microsecond=0)


class CsvWriter:
    def __init__(self, path: str, header: List[str], compress: bool):
        self.path = path
        self.header = header
        self.compress = compress
        os.makedirs(os.path.dirname(path), exist_ok=True)
        exists = os.path.exists(path)
        if compress:
            self.fp = gzip.open(path, "at", encoding="utf-8", newline="")
        else:
            self.fp = open(path, "a", encoding="utf-8", newline="")
        self.writer = csv.writer(self.fp)
        if not exists:
            self.writer.writerow(header)

    def write_row(self, row: List):
        self.writer.writerow(row)
        self.fp.flush()

    def close(self):
        self.fp.close()


class WriterManager:
    def __init__(self, base_dir: str, split_minutes: int, compress: bool):
        self.base_dir = base_dir
        self.split_minutes = split_minutes
        self.compress = compress
        self.open_files: Dict[Tuple, CsvWriter] = {}

    def _path(self, kind: str, bucket: dt.datetime, device_id: str, channel: str = "") -> str:
        base = os.path.join(self.base_dir, kind, bucket.strftime("%Y"), bucket.strftime("%m"), bucket.strftime("%d"), bucket.strftime("%H"))
        ts = bucket.strftime("%Y%m%d_%H%M")
        ext = ".csv.gz" if self.compress else ".csv"
        if kind == "waveform_csv":
            name = f"{device_id}_{ts}_{channel}{ext}"
        elif kind == "events_csv":
            name = f"{device_id}_{ts}_alarm{ext}"
        elif kind == "numerics_csv":
            name = f"{device_id}_{ts}_vitals{ext}"
        else:
            name = f"{device_id}_{ts}{ext}"
        return os.path.join(base, name)

    def get_waveform_writer(self, bucket: dt.datetime, device_id: str, channel: str) -> CsvWriter:
        key = ("waveform", bucket, device_id, channel)
        if key not in self.open_files:
            path = self._path("waveform_csv", bucket, device_id, channel)
            header = [
                "device_id",
                "channel_code",
                "channel_name",
                "start_time",
                "end_time",
                "sample_rate",
                "resolution",
                "unit",
                "samples",
                "samples_count",
                "inop",
            ]
            self.open_files[key] = CsvWriter(path, header, self.compress)
        return self.open_files[key]

    def get_event_writer(self, bucket: dt.datetime, device_id: str) -> CsvWriter:
        key = ("event", bucket, device_id)
        if key not in self.open_files:
            path = self._path("events_csv", bucket, device_id)
            header = ["device_id", "event_code", "event_name", "event_phase", "alarm_state", "priority", "timestamp"]
            self.open_files[key] = CsvWriter(path, header, self.compress)
        return self.open_files[key]

    def get_numerics_writer(self, bucket: dt.datetime, device_id: str) -> CsvWriter:
        key = ("numerics", bucket, device_id)
        if key not in self.open_files:
            path = self._path("numerics_csv", bucket, device_id)
            header = ["device_id", "timestamp", "code", "name", "value", "unit"]
            self.open_files[key] = CsvWriter(path, header, self.compress)
        return self.open_files[key]

    def close_all(self):
        for w in self.open_files.values():
            w.close()
        self.open_files.clear()


def write_raw_hl7(base_dir: str, bucket: dt.datetime, device_id: str, msg: str, compress: bool):
    path = os.path.join(
        base_dir,
        "raw_hl7",
        bucket.strftime("%Y"),
        bucket.strftime("%m"),
        bucket.strftime("%d"),
        bucket.strftime("%H"),
        f"{device_id}_{bucket.strftime('%Y%m%d_%H%M')}.hl7" + (".gz" if compress else "")
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if compress:
        fp = gzip.open(path, "at", encoding="utf-8")
    else:
        fp = open(path, "a", encoding="utf-8")
    fp.write(msg)
    fp.write("\n\n")
    fp.close()


def run_server(cfg: Dict):
    listen_ip = cfg["listen_ip"]
    listen_port = cfg["listen_port"]
    device_id_cfg = cfg.get("device_id", "")
    split_minutes = cfg.get("split_minutes", 1)
    compress = cfg.get("compress", True)
    enable_ack = cfg.get("enable_ack", True)
    base_dir = cfg.get("data_dir", "data")

    writer_mgr = WriterManager(base_dir, split_minutes, compress)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen_ip, listen_port))
    srv.listen(1)
    log(f"Listening on {listen_ip}:{listen_port}")

    while True:
        conn, addr = srv.accept()
        log(f"Connected from {addr}")
        conn.settimeout(10.0)
        buffer = bytearray()
        try:
            while True:
                try:
                    data = conn.recv(8192)
                except socket.timeout:
                    continue
                if not data:
                    break
                frames = decode_mllp_frames(data, buffer)
                for frame in frames:
                    msg_text = frame.decode("utf-8", errors="replace")
                    segments = [s for s in msg_text.replace("\n", "\r").split("\r") if s]
                    if not segments or not segments[0].startswith("MSH"):
                        continue
                    msh_fields = segments[0].split("|")
                    msg_time = parse_hl7_timestamp(msh_fields[6] if len(msh_fields) > 6 else "")
                    msg_type = msh_fields[8] if len(msh_fields) > 8 else ""
                    device_id = device_id_cfg or extract_device_id(msh_fields[2] if len(msh_fields) > 2 else "") or "UNKNOWN"

                    if msg_time is None:
                        msg_time = dt.datetime.now(dt.timezone.utc).astimezone()

                    if cfg.get("write_raw_hl7", True):
                        bucket = bucket_time(msg_time, split_minutes)
                        write_raw_hl7(base_dir, bucket, device_id, msg_text, compress)

                    if msg_type.startswith("ORU^R01") and cfg.get("write_waveforms", True):
                        obr_start, obr_end, channels, numerics = process_oru_r01(segments)
                        if obr_start is None:
                            obr_start = msg_time
                        if obr_end is None:
                            obr_end = obr_start
                        bucket = bucket_time(obr_start, split_minutes)
                        for ch in channels:
                            writer = writer_mgr.get_waveform_writer(bucket, device_id, ch.get("channel_code") or "UNKNOWN")
                            samples = ch.get("samples") or ""
                            samples_count = samples.count("^") + 1 if samples else 0
                            writer.write_row([
                                device_id,
                                ch.get("channel_code", ""),
                                ch.get("channel_name", ""),
                                obr_start.isoformat(),
                                obr_end.isoformat(),
                                ch.get("sample_rate") or "",
                                ch.get("resolution") or "",
                                ch.get("unit") or "",
                                samples,
                                samples_count,
                                ch.get("inop", ""),
                            ])
                        if numerics:
                            ts_iso = obr_start.isoformat()
                            writer = writer_mgr.get_numerics_writer(bucket, device_id)
                            for nm in numerics:
                                writer.write_row([
                                    device_id,
                                    ts_iso,
                                    nm.get("code", ""),
                                    nm.get("name", ""),
                                    nm.get("value") if nm.get("value") is not None else "",
                                    nm.get("unit", ""),
                                ])

                    if msg_type.startswith("ORU^R40") and cfg.get("write_events", True):
                        event = process_oru_r40(segments)
                        ts = event.get("timestamp") or msg_time
                        bucket = bucket_time(ts, split_minutes)
                        writer = writer_mgr.get_event_writer(bucket, device_id)
                        writer.write_row([
                            device_id,
                            event.get("event_code", ""),
                            event.get("event_name", ""),
                            event.get("event_phase", ""),
                            event.get("alarm_state", ""),
                            event.get("priority", ""),
                            ts.isoformat() if ts else "",
                        ])

                    if enable_ack:
                        ack = build_ack(msg_text, cfg.get("ack_app", "RECV"), cfg.get("ack_facility", "RECV"))
                        conn.sendall(ack)
        except Exception as e:
            log(f"Connection error: {e}")
        finally:
            conn.close()
            log("Disconnected")


def main():
    parser = argparse.ArgumentParser(description="Mindray HL7 collector")
    parser.add_argument("--config", default="config.json", help="config file (json)")
    args = parser.parse_args()
    cfg = load_config(args.config)
    upload_cfg = cfg.get("upload", {})
    if upload_cfg.get("enabled") and upload_cfg.get("run_in_background", True):
        try:
            from uploader import run_uploader
            t = threading.Thread(target=run_uploader, args=(cfg, False, log), daemon=True)
            t.start()
            log("Uploader thread started")
        except Exception as e:
            log(f"Uploader disabled: {e}")
    run_server(cfg)


if __name__ == "__main__":
    main()
