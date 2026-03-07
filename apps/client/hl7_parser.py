"""Shared HL7 v2.6 / MLLP parsing utilities.

Used by both the CLI collector and the PhysRecorder GUI.
"""

import datetime as dt
import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# MLLP framing constants
# ---------------------------------------------------------------------------

MLLP_START = b"\x0b"
MLLP_END = b"\x1c\x0d"

# ---------------------------------------------------------------------------
# HL7 unit mapping
# ---------------------------------------------------------------------------

UNIT_MAP = {
    "MDC_DIM_MILLI_VOLT": "mV",
    "MDC_DIM_DIMLESS": "1",
    "MDC_DIM_HZ": "Hz",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_hl7_timestamp(s: str) -> Optional[dt.datetime]:
    """Parse an HL7 timestamp (YYYYMMDDHHMMSSfff[+-]HHMM) into a datetime."""
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


def safe_unit(units_field: str) -> str:
    """Extract a human-readable unit from an HL7 units field."""
    parts = units_field.split("^") if units_field else []
    if len(parts) >= 2:
        return UNIT_MAP.get(parts[1], parts[1])
    return ""


def extract_device_id(msh3: str) -> str:
    """Extract a 12-char hex device ID from the MSH-3 field."""
    if not msh3:
        return ""
    parts = msh3.split("^")
    for p in parts:
        if re.fullmatch(r"[0-9A-Fa-f]{12}", p):
            return p.upper()
    return ""


def parse_obs_id(obs_id: str) -> Tuple[str, str]:
    """Split an observation identifier into (code, name)."""
    parts = obs_id.split("^") if obs_id else []
    code = parts[0] if len(parts) > 0 else ""
    name = parts[1] if len(parts) > 1 else ""
    return code, name


# ---------------------------------------------------------------------------
# MLLP frame decoding
# ---------------------------------------------------------------------------

def decode_mllp_frames(data: bytes, buffer: bytearray) -> List[bytes]:
    """Extract complete MLLP frames from *data*, using *buffer* for leftovers."""
    buffer.extend(data)
    frames: List[bytes] = []
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


# ---------------------------------------------------------------------------
# ACK builder
# ---------------------------------------------------------------------------

def build_ack(msg_text: str, ack_app: str, ack_fac: str) -> bytes:
    """Build an MLLP-framed HL7 ACK for *msg_text*."""
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


# ---------------------------------------------------------------------------
# ORU message processors
# ---------------------------------------------------------------------------

def process_oru_r01(segments: List[str]) -> Tuple[Optional[dt.datetime], Optional[dt.datetime], List[Dict], List[Dict]]:
    """Parse an ORU^R01 (waveform) message and return (start, end, channels, numerics)."""
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
    numerics: List[Dict] = []
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
        elif value_type == "NM" and current is not None:
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
        elif value_type == "NM" and current is None:
            # Standalone numeric vital sign parameter
            try:
                num_value = float(value)
            except (ValueError, TypeError):
                num_value = None
            numerics.append({
                "code": obs_code,
                "name": obs_name or obs_code,
                "value": num_value,
                "unit": safe_unit(units),
            })
        elif value_type == "ST" and current is not None:
            if obs_code == "196660" and "MDC_EVT_INOP" in obs_id:
                current["inop"] = value
    return obr_start, obr_end, channels, numerics


def process_oru_r40(segments: List[str]) -> Dict:
    """Parse an ORU^R40 (alarm/event) message and return an event dict."""
    event: Dict = {
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
