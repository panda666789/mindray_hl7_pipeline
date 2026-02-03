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

MLLP_START = b"\x0b"
MLLP_END = b"\x1c\x0d"

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

UNIT_MAP = {
    "MDC_DIM_MILLI_VOLT": "mV",
    "MDC_DIM_DIMLESS": "1",
    "MDC_DIM_HZ": "Hz",
}


def log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


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


def parse_hl7_timestamp(s: str) -> Optional[dt.datetime]:
    if not s:
        return None
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{0,4})([+-]\d{4})?$", s)
    if not m:
        return None
    year, mon, day, hh, mm, ss, frac, tz = m.groups()
    micro = 0
    if frac:
        if len(frac) <= 3:
            micro = int(frac.ljust(3, "0")) * 1000
        else:
            micro = int(frac.ljust(6, "0")[:6])
    tzinfo = None
    if tz:
        sign = 1 if tz[0] == "+" else -1
        tzh = int(tz[1:3])
        tzm = int(tz[3:5])
        offset = sign * (tzh * 60 + tzm)
        tzinfo = dt.timezone(dt.timedelta(minutes=offset))
    try:
        return dt.datetime(int(year), int(mon), int(day), int(hh), int(mm), int(ss), micro, tzinfo=tzinfo)
    except Exception:
        return None


def bucket_time(ts: dt.datetime, minutes: int) -> dt.datetime:
    minute = ts.minute - (ts.minute % minutes)
    return ts.replace(minute=minute, second=0, microsecond=0)


def safe_unit(units_field: str) -> str:
    parts = units_field.split("^") if units_field else []
    if len(parts) >= 2:
        return UNIT_MAP.get(parts[1], parts[1])
    return ""


def extract_device_id(msh3: str) -> str:
    if not msh3:
        return ""
    parts = msh3.split("^")
    for p in parts:
        if re.fullmatch(r"[0-9A-Fa-f]{12}", p):
            return p.upper()
    return ""


def parse_obs_id(obs_id: str) -> Tuple[str, str]:
    parts = obs_id.split("^") if obs_id else []
    code = parts[0] if len(parts) > 0 else ""
    name = parts[1] if len(parts) > 1 else ""
    return code, name


def decode_mllp_frames(data: bytes, buffer: bytearray) -> List[bytes]:
    buffer.extend(data)
    frames = []
    while True:
        start = buffer.find(MLLP_START)
        if start < 0:
            buffer.clear()
            break
        end = buffer.find(MLLP_END, start + 1)
        if end < 0:
            if start > 0:
                del buffer[:start]
            break
        frame = bytes(buffer[start + 1:end])
        del buffer[:end + 2]
        frames.append(frame)
    return frames


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


def build_ack(msg_text: str, ack_app: str, ack_fac: str) -> bytes:
    segs = msg_text.split("\r")
    msh = segs[0].split("|") if segs else []
    send_app = msh[2] if len(msh) > 2 else ""
    send_fac = msh[3] if len(msh) > 3 else ""
    msg_id = msh[9] if len(msh) > 9 else ""
    ver = msh[11] if len(msh) > 11 else "2.6"
    ts = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    ack = f"MSH|^~\\&|{ack_app}|{ack_fac}|{send_app}|{send_fac}|{ts}||ACK|{msg_id}-ACK|P|{ver}\rMSA|AA|{msg_id}\r"
    b = ack.encode("utf-8")
    return MLLP_START + b + MLLP_END


def process_oru_r01(segments: List[str]) -> Tuple[Optional[dt.datetime], Optional[dt.datetime], List[Dict]]:
    obr_start = None
    obr_end = None
    for seg in segments:
        if seg.startswith("OBR|"):
            fields = seg.split("|")
            if len(fields) > 7:
                obr_start = parse_hl7_timestamp(fields[7])
            if len(fields) > 8:
                obr_end = parse_hl7_timestamp(fields[8])
            break

    channels: List[Dict] = []
    current = None
    for seg in segments:
        if not seg.startswith("OBX|"):
            continue
        fields = seg.split("|")
        if len(fields) < 6:
            continue
        value_type = fields[2]
        obs_id = fields[3]
        obs_code, obs_name = parse_obs_id(obs_id)
        value = fields[5]
        units = fields[6] if len(fields) > 6 else ""
        if value_type == "NA":
            current = {
                "channel_code": obs_name or obs_code,
                "channel_name": obs_name,
                "samples": value,
                "sample_rate": None,
                "resolution": None,
                "unit": "",
                "inop": "",
            }
            channels.append(current)
        else:
            if current is None:
                continue
            if obs_code == "0" and "MDC_ATTR_SAMP_RATE" in obs_id:
                try:
                    current["sample_rate"] = float(value)
                except Exception:
                    current["sample_rate"] = None
            elif obs_code == "2327" and "MDC_ATTR_NU_MSMT_RES" in obs_id:
                try:
                    current["resolution"] = float(value)
                except Exception:
                    current["resolution"] = None
                current["unit"] = safe_unit(units)
            elif obs_code == "196660" and "MDC_EVT_INOP" in obs_id:
                current["inop"] = value
    return obr_start, obr_end, channels


def process_oru_r40(segments: List[str]) -> Dict:
    event = {
        "event_code": "",
        "event_name": "",
        "event_phase": "",
        "alarm_state": "",
        "priority": "",
        "timestamp": None,
    }
    for seg in segments:
        if not seg.startswith("OBX|"):
            continue
        fields = seg.split("|")
        if len(fields) < 6:
            continue
        obs_id = fields[3]
        obs_code, _ = parse_obs_id(obs_id)
        value = fields[5]
        if obs_code == "196616":
            vcode, vname = parse_obs_id(value)
            event["event_code"] = vcode
            event["event_name"] = vname
            if len(fields) > 14:
                ts = parse_hl7_timestamp(fields[14])
                if ts:
                    event["timestamp"] = ts
        elif obs_code == "68481":
            event["event_phase"] = value
        elif obs_code == "68482":
            event["alarm_state"] = value
        elif obs_code == "68484":
            event["priority"] = value
    return event


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
                        obr_start, obr_end, channels = process_oru_r01(segments)
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
