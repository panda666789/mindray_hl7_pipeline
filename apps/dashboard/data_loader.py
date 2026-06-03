"""Data loader for the Mindray dashboard.

Reads PhysRecorder format: <session>/<DeviceName>/...csv
"""

import glob
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

# ── Display name mappings ────────────────────────────────────────────

UNIT_DISPLAY = {
    "MDC_DIM_BEAT_PER_MIN": "bpm",
    "MDC_DIM_RESP_PER_MIN": "次/分",
    "MDC_DIM_PERCENT": "%",
    "MDC_DIM_MMHG": "mmHg",
    "MDC_DIM_DEGC": "°C",
    "MDC_DIM_MILLI_VOLT": "mV",
    "MDC_DIM_HZ": "Hz",
    "MDC_DIM_DIMLESS": "",
}

NAME_DISPLAY = {
    "MDC_ECG_HEART_RATE": "心率 (HR)",
    "MDC_TTHOR_RESP_RATE": "呼吸率 (RR)",
    "MDC_PULS_OXIM_SAT_O2": "血氧 (SpO2)",
    "MDC_PRESS_BLD_ART_ABP_SYS": "收缩压",
    "MDC_PRESS_BLD_ART_ABP_DIA": "舒张压",
    "MDC_PRESS_BLD_ART_ABP_MEAN": "平均动脉压",
    "MDC_TEMP": "体温",
    "MDC_ECG_V_P_C_RATE": "PVC 频率",
    "MNDRY_ECG_PAUSE_RATE": "心电暂停",
    "MNDRY_ECG_VPB_RATE": "室性早搏",
    "MNDRY_ECG_COUPLETS_RATE": "成对早搏",
    "MNDRY_ECG_MISSED_BEATS_RATE": "漏搏",
    "MNDRY_ECG_P_V_C_RonT_RATE": "R-on-T",
}

CHANNEL_DISPLAY = {
    "MDC_ECG_ELEC_POTL_I": "ECG I",
    "MDC_ECG_ELEC_POTL_II": "ECG II",
    "MDC_ECG_ELEC_POTL_III": "ECG III",
    "MDC_ECG_ELEC_POTL_AVR": "ECG aVR",
    "MDC_ECG_ELEC_POTL_AVL": "ECG aVL",
    "MDC_ECG_ELEC_POTL_AVF": "ECG aVF",
    "MDC_ECG_ELEC_POTL_V": "ECG V",
    "MDC_PULS_OXIM_PLETH": "SpO2 脉搏波",
    "MDC_IMPED_TTHOR": "呼吸阻抗",
}


def friendly_unit(mdc_unit: str) -> str:
    return UNIT_DISPLAY.get(str(mdc_unit).strip(), str(mdc_unit))


def friendly_name(mdc_name: str) -> str:
    return NAME_DISPLAY.get(str(mdc_name).strip(), str(mdc_name))


def friendly_channel(channel_code: str) -> str:
    return CHANNEL_DISPLAY.get(str(channel_code).strip(), str(channel_code))


# ── Session scanning ─────────────────────────────────────────────────

# Known data files that indicate a recording session exists in a subdirectory
_KNOWN_FILES = {
    "waveforms.csv", "vitals.csv", "events.csv",           # MindrayHL7
    "signals.csv", "sensor1.csv",                           # Ring/OmniRing/OmniRingCom/HUB/Glasses
    "bvp.csv", "spo2.csv", "hr.csv",                       # PulseOximeter
    "resp.csv",                                             # KHK11CP
    "video.avi", "metadata.csv", "timestamps.csv",          # Camera
}


def scan_sessions(data_dir: str) -> List[Dict]:
    """Scan data directory for recording sessions.

    A session is a leaf-level directory that directly contains known data files,
    OR whose immediate children contain known data files (device subdirectories).
    When both parent and child qualify, only the child (more specific) is kept.
    """
    sessions = []
    if not os.path.isdir(data_dir):
        return sessions

    for root, dirs, files in os.walk(data_dir):
        # Check if current directory contains known data files directly
        has_direct = any(f in _KNOWN_FILES for f in files)
        # Check if any immediate subdirectory contains known data files
        has_subdir_data = False
        for d in dirs:
            sub = os.path.join(root, d)
            try:
                sub_files = os.listdir(sub)
            except OSError:
                continue
            if any(f in _KNOWN_FILES for f in sub_files):
                has_subdir_data = True
                break

        if not has_direct and not has_subdir_data:
            continue

        # Collect all data files (direct + subdirectories) for mtime
        all_data_files = []
        if has_direct:
            all_data_files.extend(
                os.path.join(root, f) for f in files if f in _KNOWN_FILES
            )
        for d in dirs:
            sub = os.path.join(root, d)
            try:
                sub_files = os.listdir(sub)
            except OSError:
                continue
            all_data_files.extend(
                os.path.join(sub, f) for f in sub_files if f in _KNOWN_FILES
            )

        if not all_data_files:
            continue

        mtime = max(os.path.getmtime(f) for f in all_data_files)
        rel = os.path.relpath(root, data_dir)

        sessions.append({
            "path": root,
            "name": rel,
            "mtime": datetime.fromtimestamp(mtime),
        })

    # Deduplicate: if both parent and child are sessions, keep only the child
    # (the more specific one that actually holds the data).
    child_paths = set()
    for s in sessions:
        for other in sessions:
            if other["path"] != s["path"] and other["path"].startswith(s["path"] + os.sep):
                child_paths.add(other["path"])
    # Remove parents that have children in the list
    parent_paths = set()
    for s in sessions:
        for other in sessions:
            if other["path"] != s["path"] and other["path"].startswith(s["path"] + os.sep):
                parent_paths.add(s["path"])
    sessions = [s for s in sessions if s["path"] not in parent_paths]

    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


# ── Helpers ──────────────────────────────────────────────────────────

def _find_file(session_path: str, filename: str) -> Optional[str]:
    """Find a file in session root or any immediate subdirectory."""
    direct = os.path.join(session_path, filename)
    if os.path.exists(direct):
        return direct
    for d in _list_subdirs(session_path):
        p = os.path.join(session_path, d, filename)
        if os.path.exists(p):
            return p
    return None


def _find_files_pattern(session_path: str, pattern: str) -> List[str]:
    """Find files matching a glob pattern in session root and subdirectories."""
    results = glob.glob(os.path.join(session_path, pattern))
    results += glob.glob(os.path.join(session_path, "*", pattern))
    return sorted(results)


def _list_subdirs(session_path: str) -> List[str]:
    try:
        return [
            d for d in os.listdir(session_path)
            if os.path.isdir(os.path.join(session_path, d))
        ]
    except OSError:
        return []


def _safe_read_csv(path: str) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(path)
        return df if not df.empty else None
    except Exception:
        return None


# ── Mindray HL7 loaders ─────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_waveforms(session_path: str) -> Optional[pd.DataFrame]:
    path = _find_file(session_path, "waveforms.csv")
    return _safe_read_csv(path) if path else None


@st.cache_data(ttl=30)
def load_vitals(session_path: str) -> Optional[pd.DataFrame]:
    path = _find_file(session_path, "vitals.csv")
    return _safe_read_csv(path) if path else None


@st.cache_data(ttl=30)
def load_events(session_path: str) -> Optional[pd.DataFrame]:
    path = _find_file(session_path, "events.csv")
    return _safe_read_csv(path) if path else None


# ── PPG Ring loaders (OmniRing / OmniRingCom / Ring) ────────────────

_PPG_IMU_COLS = ["timestamp", "red", "ir", "green", "ax", "ay", "az",
                 "rx", "ry", "rz", "mx", "my", "mz", "time"]
_RING_COLS = ["timestamp", "green", "red", "ir", "ax", "ay", "az",
              "gx", "gy", "gz", "t0", "t1", "t2", "time"]


@st.cache_data(ttl=30)
def load_ppg_ring_data(session_path: str) -> List[Dict]:
    """Load PPG ring/omni-ring data. Returns list of {name, df, columns_type}."""
    results = []
    for subdir in _list_subdirs(session_path):
        lower = subdir.lower()
        sub_path = os.path.join(session_path, subdir)

        if "omniring" in lower and "com" not in lower:
            # OmniRing -> signals.csv
            p = os.path.join(sub_path, "signals.csv")
            df = _safe_read_csv(p)
            if df is not None:
                results.append({"name": subdir, "df": df, "type": "ppg_imu"})

        elif "omniringcom" in lower or "omniring" in lower and "com" in lower:
            # OmniRingCom -> sensor1.csv
            p = os.path.join(sub_path, "sensor1.csv")
            df = _safe_read_csv(p)
            if df is not None:
                results.append({"name": subdir, "df": df, "type": "ppg_imu"})

        elif lower.startswith("ring"):
            # Ring -> signals.csv
            p = os.path.join(sub_path, "signals.csv")
            df = _safe_read_csv(p)
            if df is not None:
                results.append({"name": subdir, "df": df, "type": "ring"})

    return results


# ── HUB loader ───────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_hub_data(session_path: str) -> List[Dict]:
    """Load HUB multi-channel data. Returns list of {channel, df}."""
    results = []
    for subdir in _list_subdirs(session_path):
        if subdir.lower() != "hub":
            continue
        sub_path = os.path.join(session_path, subdir)
        for i in range(1, 9):
            p = os.path.join(sub_path, f"sensor{i}.csv")
            df = _safe_read_csv(p)
            if df is not None:
                results.append({"channel": i, "df": df})
    return results


# ── Glasses loader ───────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_glasses_data(session_path: str) -> List[Dict]:
    """Load glasses eye-tracking data. Returns list of {sensor, df}."""
    results = []
    for subdir in _list_subdirs(session_path):
        if subdir.lower() != "glasses":
            continue
        sub_path = os.path.join(session_path, subdir)
        for i in (1, 2):
            p = os.path.join(sub_path, f"sensor{i}.csv")
            df = _safe_read_csv(p)
            if df is not None:
                results.append({"sensor": i, "df": df})
    return results


# ── Pulse Oximeter loader ────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_oximeter_data(session_path: str) -> Optional[Dict]:
    """Load pulse oximeter data. Returns {bvp, spo2, hr} DataFrames or None."""
    for subdir in _list_subdirs(session_path):
        if subdir.lower() != "oximeter":
            continue
        sub_path = os.path.join(session_path, subdir)
        bvp = _safe_read_csv(os.path.join(sub_path, "bvp.csv"))
        spo2 = _safe_read_csv(os.path.join(sub_path, "spo2.csv"))
        hr = _safe_read_csv(os.path.join(sub_path, "hr.csv"))
        if bvp is not None or spo2 is not None or hr is not None:
            return {"bvp": bvp, "spo2": spo2, "hr": hr}
    return None


# ── Respiration meter loader ─────────────────────────────────────────

@st.cache_data(ttl=30)
def load_respiration_data(session_path: str) -> Optional[pd.DataFrame]:
    """Load KHK11CP respiration meter data."""
    for subdir in _list_subdirs(session_path):
        if "respiration" in subdir.lower():
            p = os.path.join(session_path, subdir, "resp.csv")
            return _safe_read_csv(p)
    return None


# ── Camera loader ────────────────────────────────────────────────────

@st.cache_data(ttl=30)
def load_camera_data(session_path: str) -> List[Dict]:
    """Load camera metadata. Returns list of {name, metadata_df, timestamps_df, video_path}."""
    results = []
    for subdir in _list_subdirs(session_path):
        if not subdir.lower().startswith("camera"):
            continue
        sub_path = os.path.join(session_path, subdir)
        meta = _safe_read_csv(os.path.join(sub_path, "metadata.csv"))
        ts = _safe_read_csv(os.path.join(sub_path, "timestamps.csv"))
        video = os.path.join(sub_path, "video.avi")
        has_video = os.path.exists(video)
        if meta is not None or ts is not None or has_video:
            results.append({
                "name": subdir,
                "metadata": meta,
                "timestamps": ts,
                "video_path": video if has_video else None,
                "video_size_mb": round(os.path.getsize(video) / 1048576, 1) if has_video else 0,
            })
    return results


# ── Waveform utilities ───────────────────────────────────────────────

def parse_waveform_samples(row: pd.Series) -> Tuple[List[float], float]:
    """Parse a waveform row into physical values and time step."""
    samples_str = str(row.get("samples", ""))
    resolution = float(row.get("resolution", 1.0))
    sample_rate = float(row.get("sample_rate", 1.0))

    if not samples_str or samples_str == "nan":
        return [], 0.0

    raw = [int(s) for s in samples_str.split("^") if s.strip()]
    values = [v * resolution for v in raw]
    dt = 1.0 / sample_rate if sample_rate > 0 else 0.0
    return values, dt


def is_channel_connected(df_channel: pd.DataFrame) -> bool:
    """Check if a channel has real data (not all 32767 = sensor disconnected)."""
    first_row = df_channel.iloc[0]
    samples_str = str(first_row.get("samples", ""))
    if not samples_str or samples_str == "nan":
        return False
    raw = [int(s) for s in samples_str.split("^") if s.strip()]
    return not all(v == 32767 for v in raw)
