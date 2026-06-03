"""Mindray physiological data dashboard.

Usage:
    DATA_DIR=/path/to/data streamlit run apps/dashboard/app.py --server.port 8501
"""

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from data_loader import (
    friendly_channel,
    friendly_name,
    friendly_unit,
    is_channel_connected,
    load_camera_data,
    load_events,
    load_glasses_data,
    load_hub_data,
    load_oximeter_data,
    load_ppg_ring_data,
    load_respiration_data,
    load_vitals,
    load_waveforms,
    parse_waveform_samples,
    scan_sessions,
)

st.set_page_config(page_title="生理数据看板", page_icon="🏥", layout="wide")
DATA_DIR = os.environ.get("DATA_DIR", "data")

# ── Sidebar ──────────────────────────────────────────────────────────
st.sidebar.title("📂 录制会话")
sessions = scan_sessions(DATA_DIR)

if not sessions:
    st.warning(f"未找到数据。请确认 `{DATA_DIR}` 目录下有录制文件。")
    st.stop()

session_names = [f"{s['name']}  ({s['mtime'].strftime('%m-%d %H:%M')})" for s in sessions]
selected_idx = st.sidebar.selectbox("选择会话", range(len(session_names)),
                                     format_func=lambda i: session_names[i])
session = sessions[selected_idx]

st.sidebar.markdown(f"**更新时间**: {session['mtime'].strftime('%Y-%m-%d %H:%M:%S')}")

# ── Load all data ────────────────────────────────────────────────────
df_wave = load_waveforms(session["path"])
df_vitals = load_vitals(session["path"])
df_events = load_events(session["path"])
ppg_rings = load_ppg_ring_data(session["path"])
hub_data = load_hub_data(session["path"])
glasses_data = load_glasses_data(session["path"])
oximeter_data = load_oximeter_data(session["path"])
resp_data = load_respiration_data(session["path"])
camera_data = load_camera_data(session["path"])

# ── Sidebar summary ──────────────────────────────────────────────────
avail = []
if df_wave is not None and not df_wave.empty:
    avail.append(f"✅ 波形 ({len(df_wave)} 条)")
if df_vitals is not None and not df_vitals.empty:
    avail.append(f"✅ 体征 ({len(df_vitals)} 条)")
if df_events is not None and not df_events.empty:
    avail.append(f"✅ 事件 ({len(df_events)} 条)")
if ppg_rings:
    avail.append(f"✅ PPG指环 ({len(ppg_rings)} 个)")
if hub_data:
    avail.append(f"✅ HUB ({len(hub_data)} 通道)")
if glasses_data:
    avail.append(f"✅ 眼动眼镜 ({len(glasses_data)} 传感器)")
if oximeter_data:
    avail.append("✅ 脉搏血氧仪")
if resp_data is not None:
    avail.append(f"✅ 呼吸仪 ({len(resp_data)} 条)")
if camera_data:
    avail.append(f"✅ 摄像头 ({len(camera_data)} 路)")
st.sidebar.markdown("  \n".join(avail) if avail else "❌ 无数据")

# ── Build tabs dynamically ───────────────────────────────────────────
tab_labels = ["📊 概览", "📈 波形查看", "💓 生命体征", "🚨 事件记录"]
has_peripherals = any([ppg_rings, hub_data, glasses_data, oximeter_data,
                       resp_data is not None, camera_data])
if ppg_rings:
    tab_labels.append("💍 PPG指环")
if hub_data:
    tab_labels.append("🔌 HUB多通道")
if glasses_data:
    tab_labels.append("👓 眼动眼镜")
if oximeter_data:
    tab_labels.append("🫀 脉搏血氧仪")
if resp_data is not None:
    tab_labels.append("🌬️ 呼吸仪")
if camera_data:
    tab_labels.append("📷 摄像头")

tabs = st.tabs(tab_labels)
tab_iter = iter(tabs)

# ── Tab 1: Overview ──────────────────────────────────────────────────
with next(tab_iter):
    st.header("数据概览")

    if df_vitals is not None and not df_vitals.empty:
        st.subheader("最新生命体征")
        key_vitals = ["MDC_ECG_HEART_RATE", "MDC_TTHOR_RESP_RATE", "MDC_PULS_OXIM_SAT_O2"]
        cols = st.columns(len(key_vitals))
        for i, vn in enumerate(key_vitals):
            rows = df_vitals[df_vitals["name"] == vn]
            with cols[i]:
                if not rows.empty:
                    val = rows.iloc[-1]["value"]
                    unit = friendly_unit(rows.iloc[-1].get("unit", ""))
                    st.metric(friendly_name(vn), f"{val:.0f}" if pd.notna(val) else "—", unit)
                else:
                    st.metric(friendly_name(vn), "—")

        st.subheader("全部体征参数")
        dv = df_vitals.copy()
        dv["参数名称"] = dv["name"].apply(friendly_name)
        dv["单位"] = dv["unit"].apply(friendly_unit)
        st.dataframe(dv[["参数名称", "value", "单位"]].rename(columns={"value": "数值"}),
                     use_container_width=True, hide_index=True)
    else:
        st.info("无生命体征数据")

    if df_wave is not None and not df_wave.empty:
        st.subheader("采集通道")
        info = []
        for ch in df_wave["channel_code"].unique():
            ch_rows = df_wave[df_wave["channel_code"] == ch]
            first = ch_rows.iloc[0]
            info.append({
                "通道": friendly_channel(ch),
                "采样率": f"{first['sample_rate']:.0f} Hz",
                "单位": first.get("unit", ""),
                "数据条数": len(ch_rows),
                "状态": "✅ 正常" if is_channel_connected(ch_rows) else "❌ 未接入",
            })
        st.dataframe(pd.DataFrame(info), use_container_width=True, hide_index=True)

    if df_events is not None and not df_events.empty:
        st.subheader("最近告警事件")
        st.dataframe(df_events.tail(10), use_container_width=True, hide_index=True)
    else:
        st.info("无告警事件")

    # Peripheral summary
    if has_peripherals:
        st.subheader("外设数据概览")
        periph_info = []
        for ring in ppg_rings:
            periph_info.append({"设备": ring["name"], "类型": "PPG指环", "数据量": f"{len(ring['df'])} 条"})
        if hub_data:
            periph_info.append({"设备": "HUB", "类型": "多通道采集器", "数据量": f"{len(hub_data)} 通道"})
        for g in glasses_data:
            periph_info.append({"设备": f"眼动眼镜 传感器{g['sensor']}", "类型": "眼动", "数据量": f"{len(g['df'])} 条"})
        if oximeter_data:
            parts = []
            for k, label in [("bvp", "BVP"), ("spo2", "SpO2"), ("hr", "HR")]:
                if oximeter_data[k] is not None:
                    parts.append(f"{label}: {len(oximeter_data[k])}条")
            periph_info.append({"设备": "脉搏血氧仪", "类型": "血氧", "数据量": ", ".join(parts)})
        if resp_data is not None:
            periph_info.append({"设备": "呼吸仪", "类型": "呼吸", "数据量": f"{len(resp_data)} 条"})
        for cam in camera_data:
            size = f"{cam['video_size_mb']} MB" if cam["video_path"] else "无视频"
            periph_info.append({"设备": cam["name"], "类型": "摄像头", "数据量": size})
        if periph_info:
            st.dataframe(pd.DataFrame(periph_info), use_container_width=True, hide_index=True)

# ── Tab 2: Waveform viewer ──────────────────────────────────────────
with next(tab_iter):
    st.header("波形查看")

    if df_wave is None or df_wave.empty:
        st.info("无波形数据")
    else:
        channels = df_wave["channel_code"].unique().tolist()
        labels = {ch: friendly_channel(ch) for ch in channels}

        active = [ch for ch in channels if is_channel_connected(df_wave[df_wave["channel_code"] == ch])]
        inactive = [ch for ch in channels if ch not in active]

        if inactive:
            st.caption(f"⚠️ 未接入: {', '.join(labels[c] for c in inactive)}")

        if not active:
            st.warning("所有通道均未接入")
        else:
            selected = st.multiselect("选择通道", active, default=active[:3],
                                       format_func=lambda c: labels[c])
            if selected:
                n_rows = len(df_wave[df_wave["channel_code"] == selected[0]])
                row_range = (0, min(4, n_rows - 1))
                if n_rows > 1:
                    row_range = st.slider("数据段（每段约1秒）", 0, n_rows - 1, row_range)

                for ch in selected:
                    ch_df = df_wave[df_wave["channel_code"] == ch].reset_index(drop=True)
                    ch_slice = ch_df.iloc[row_range[0]:row_range[1] + 1]

                    all_vals, all_t, t_off = [], [], 0.0
                    for _, row in ch_slice.iterrows():
                        vals, dt = parse_waveform_samples(row)
                        if not vals:
                            continue
                        t = [t_off + i * dt for i in range(len(vals))]
                        all_vals.extend(vals)
                        all_t.extend(t)
                        t_off = t[-1] + dt

                    if all_vals:
                        unit = ch_slice.iloc[0].get("unit", "")
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=all_t, y=all_vals, mode="lines",
                                                  name=labels[ch], line=dict(width=1)))
                        fig.update_layout(title=labels[ch], xaxis_title="时间 (秒)",
                                          yaxis_title=f"幅值 ({unit})", height=300,
                                          margin=dict(l=60, r=20, t=40, b=40))
                        st.plotly_chart(fig, use_container_width=True)

# ── Tab 3: Vital signs trend ────────────────────────────────────────
with next(tab_iter):
    st.header("生命体征趋势")

    if df_vitals is None or df_vitals.empty:
        st.info("无生命体征数据")
    else:
        names = df_vitals["name"].unique().tolist()
        vlabels = {n: friendly_name(n) for n in names}
        defaults = [n for n in names if n in
                    ("MDC_ECG_HEART_RATE", "MDC_TTHOR_RESP_RATE", "MDC_PULS_OXIM_SAT_O2")]
        selected = st.multiselect("选择参数", names, default=defaults or names[:3],
                                   format_func=lambda n: vlabels[n])

        if selected:
            for vn in selected:
                vdf = df_vitals[df_vitals["name"] == vn].copy()
                if vdf.empty:
                    continue
                try:
                    vdf["time"] = pd.to_datetime(pd.to_numeric(vdf["timestamp"]), unit="s")
                except (ValueError, TypeError):
                    vdf["time"] = pd.to_datetime(vdf["timestamp"], errors="coerce")

                unit = friendly_unit(vdf.iloc[0].get("unit", ""))
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=vdf["time"], y=vdf["value"], mode="lines+markers",
                                          name=vlabels[vn], marker=dict(size=4)))
                fig.update_layout(title=vlabels[vn], xaxis_title="时间",
                                  yaxis_title=f"数值 ({unit})", height=300,
                                  margin=dict(l=60, r=20, t=40, b=40))
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("原始数据")
        d = df_vitals.copy()
        d["参数"] = d["name"].apply(friendly_name)
        d["单位"] = d["unit"].apply(friendly_unit)
        st.dataframe(d[["timestamp", "参数", "value", "单位"]].rename(
            columns={"timestamp": "时间戳", "value": "数值"}),
            use_container_width=True, hide_index=True)

# ── Tab 4: Events ───────────────────────────────────────────────────
with next(tab_iter):
    st.header("事件记录")

    if df_events is None or df_events.empty:
        st.info("无告警事件")
    else:
        priorities = df_events["priority"].dropna().unique().tolist()
        if priorities:
            sel_pri = st.multiselect("按优先级筛选", priorities, default=priorities)
            filtered = df_events[df_events["priority"].isin(sel_pri)]
        else:
            filtered = df_events
        st.dataframe(filtered, use_container_width=True, hide_index=True)
        st.caption(f"共 {len(filtered)} 条事件")


# ── Helper: plot PPG/IMU time series ─────────────────────────────────

def _plot_ppg_imu(df: pd.DataFrame, title_prefix: str, data_type: str):
    """Render PPG and IMU charts from a sensor DataFrame."""
    if "timestamp" not in df.columns:
        st.warning("缺少 timestamp 列")
        return

    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    t = ts - ts.iloc[0]  # relative seconds

    # PPG signals
    ppg_cols = [c for c in ("red", "ir", "green") if c in df.columns]
    if ppg_cols:
        fig = go.Figure()
        for col in ppg_cols:
            fig.add_trace(go.Scatter(x=t, y=df[col], mode="lines", name=col, line=dict(width=1)))
        fig.update_layout(title=f"{title_prefix} — PPG 信号", xaxis_title="时间 (秒)",
                          yaxis_title="原始值", height=300,
                          margin=dict(l=60, r=20, t=40, b=40))
        st.plotly_chart(fig, use_container_width=True)

    # Accelerometer
    acc_cols = [c for c in ("ax", "ay", "az") if c in df.columns]
    if acc_cols:
        fig = go.Figure()
        for col in acc_cols:
            fig.add_trace(go.Scatter(x=t, y=df[col], mode="lines", name=col, line=dict(width=1)))
        fig.update_layout(title=f"{title_prefix} — 加速度计", xaxis_title="时间 (秒)",
                          yaxis_title="加速度", height=250,
                          margin=dict(l=60, r=20, t=40, b=40))
        st.plotly_chart(fig, use_container_width=True)

    # Gyroscope / Rotation
    if data_type == "ring":
        gyro_cols = [c for c in ("gx", "gy", "gz") if c in df.columns]
        label = "陀螺仪"
    else:
        gyro_cols = [c for c in ("rx", "ry", "rz") if c in df.columns]
        label = "旋转"
    if gyro_cols:
        fig = go.Figure()
        for col in gyro_cols:
            fig.add_trace(go.Scatter(x=t, y=df[col], mode="lines", name=col, line=dict(width=1)))
        fig.update_layout(title=f"{title_prefix} — {label}", xaxis_title="时间 (秒)",
                          yaxis_title="角速度", height=250,
                          margin=dict(l=60, r=20, t=40, b=40))
        st.plotly_chart(fig, use_container_width=True)

    # Temperature (Ring only)
    temp_cols = [c for c in ("t0", "t1", "t2", "temp") if c in df.columns]
    if temp_cols:
        fig = go.Figure()
        for col in temp_cols:
            fig.add_trace(go.Scatter(x=t, y=df[col], mode="lines+markers",
                                      name=col, marker=dict(size=3)))
        fig.update_layout(title=f"{title_prefix} — 温度", xaxis_title="时间 (秒)",
                          yaxis_title="温度", height=250,
                          margin=dict(l=60, r=20, t=40, b=40))
        st.plotly_chart(fig, use_container_width=True)


# ── Tab: PPG Rings ───────────────────────────────────────────────────
if ppg_rings:
    with next(tab_iter):
        st.header("PPG 指环数据")
        for ring in ppg_rings:
            st.subheader(ring["name"])
            st.caption(f"数据量: {len(ring['df'])} 条")
            _plot_ppg_imu(ring["df"], ring["name"], ring["type"])
            with st.expander("原始数据"):
                st.dataframe(ring["df"].head(200), use_container_width=True, hide_index=True)

# ── Tab: HUB ─────────────────────────────────────────────────────────
if hub_data:
    with next(tab_iter):
        st.header("HUB 多通道数据")
        ch_select = st.multiselect(
            "选择通道",
            [h["channel"] for h in hub_data],
            default=[h["channel"] for h in hub_data][:3],
            format_func=lambda c: f"通道 {c}",
        )
        for h in hub_data:
            if h["channel"] not in ch_select:
                continue
            st.subheader(f"通道 {h['channel']}")
            st.caption(f"数据量: {len(h['df'])} 条")
            _plot_ppg_imu(h["df"], f"HUB 通道{h['channel']}", "ppg_imu")

# ── Tab: Glasses ─────────────────────────────────────────────────────
if glasses_data:
    with next(tab_iter):
        st.header("眼动眼镜数据")
        for g in glasses_data:
            st.subheader(f"传感器 {g['sensor']}")
            st.caption(f"数据量: {len(g['df'])} 条")
            _plot_ppg_imu(g["df"], f"眼动 传感器{g['sensor']}", "ppg_imu")

# ── Tab: Pulse Oximeter ──────────────────────────────────────────────
if oximeter_data:
    with next(tab_iter):
        st.header("脉搏血氧仪数据")
        ox_cols = st.columns(3)

        for col_widget, (key, label, unit, color) in zip(ox_cols, [
            ("spo2", "血氧饱和度 (SpO2)", "%", "red"),
            ("hr", "心率 (HR)", "bpm", "orange"),
            ("bvp", "血容量脉搏波 (BVP)", "", "blue"),
        ]):
            with col_widget:
                df = oximeter_data.get(key)
                if df is None or df.empty:
                    st.info(f"无 {label} 数据")
                    continue
                # Show latest value as metric
                latest = df.iloc[-1]
                val_col = [c for c in df.columns if c != "timestamp"][0]
                st.metric(label, f"{latest[val_col]:.1f} {unit}")

        # Plot time series
        for key, label, color in [("spo2", "SpO2", "red"), ("hr", "HR", "orange"), ("bvp", "BVP", "blue")]:
            df = oximeter_data.get(key)
            if df is None or df.empty:
                continue
            val_col = [c for c in df.columns if c != "timestamp"][0]
            ts = pd.to_numeric(df["timestamp"], errors="coerce")
            t = ts - ts.iloc[0]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=t, y=df[val_col], mode="lines",
                                      name=label, line=dict(width=1, color=color)))
            fig.update_layout(title=label, xaxis_title="时间 (秒)", yaxis_title=label,
                              height=250, margin=dict(l=60, r=20, t=40, b=40))
            st.plotly_chart(fig, use_container_width=True)

# ── Tab: Respiration ─────────────────────────────────────────────────
if resp_data is not None:
    with next(tab_iter):
        st.header("呼吸仪数据")
        st.caption(f"数据量: {len(resp_data)} 条")
        ts = pd.to_numeric(resp_data["timestamp"], errors="coerce")
        t = ts - ts.iloc[0]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=t, y=resp_data["resp"], mode="lines",
                                  name="呼吸", line=dict(width=1, color="green")))
        fig.update_layout(title="呼吸信号", xaxis_title="时间 (秒)", yaxis_title="呼吸值",
                          height=300, margin=dict(l=60, r=20, t=40, b=40))
        st.plotly_chart(fig, use_container_width=True)
        with st.expander("原始数据"):
            st.dataframe(resp_data.head(200), use_container_width=True, hide_index=True)

# ── Tab: Camera ──────────────────────────────────────────────────────
if camera_data:
    with next(tab_iter):
        st.header("摄像头数据")
        for cam in camera_data:
            st.subheader(cam["name"])

            info_items = []
            if cam["video_path"]:
                info_items.append(f"视频文件: {cam['video_size_mb']} MB")
            if cam["timestamps"] is not None:
                info_items.append(f"帧数: {len(cam['timestamps'])}")
                ts = cam["timestamps"]
                if len(ts) > 1:
                    duration = ts["timestamp"].iloc[-1] - ts["timestamp"].iloc[0]
                    info_items.append(f"时长: {duration:.1f} 秒")
                    avg_fps = len(ts) / duration if duration > 0 else 0
                    info_items.append(f"平均帧率: {avg_fps:.1f} FPS")
            st.markdown(" | ".join(info_items) if info_items else "无详细信息")

            if cam["metadata"] is not None:
                with st.expander("摄像头参数"):
                    st.dataframe(cam["metadata"], use_container_width=True, hide_index=True)

            if cam["timestamps"] is not None and len(cam["timestamps"]) > 1:
                ts_df = cam["timestamps"].copy()
                ts_df["interval"] = ts_df["timestamp"].diff()
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=ts_df["frame"], y=ts_df["interval"] * 1000,
                                          mode="lines", name="帧间隔", line=dict(width=1)))
                fig.update_layout(title=f"{cam['name']} — 帧间隔", xaxis_title="帧号",
                                  yaxis_title="间隔 (ms)", height=250,
                                  margin=dict(l=60, r=20, t=40, b=40))
                st.plotly_chart(fig, use_container_width=True)
