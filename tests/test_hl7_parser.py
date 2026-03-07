"""Tests for the shared HL7 parser module."""

import datetime as dt
import pytest

from hl7_parser import (
    MLLP_START,
    MLLP_END,
    parse_hl7_timestamp,
    safe_unit,
    extract_device_id,
    parse_obs_id,
    decode_mllp_frames,
    build_ack,
    process_oru_r01,
    process_oru_r40,
)


# ---------------------------------------------------------------------------
# parse_hl7_timestamp
# ---------------------------------------------------------------------------

class TestParseHL7Timestamp:
    def test_full_timestamp_with_timezone(self):
        result = parse_hl7_timestamp("20260124124738000+0800")
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 24
        assert result.hour == 12
        assert result.minute == 47
        assert result.second == 38
        assert result.tzinfo is not None

    def test_timestamp_without_timezone(self):
        result = parse_hl7_timestamp("20260124131540000")
        assert result is not None
        assert result.year == 2026
        assert result.hour == 13
        assert result.tzinfo is None

    def test_timestamp_without_fractional(self):
        result = parse_hl7_timestamp("20260124131540")
        assert result is not None
        assert result.second == 40

    def test_negative_timezone(self):
        result = parse_hl7_timestamp("20260124120000000-0500")
        assert result is not None
        assert result.tzinfo == dt.timezone(dt.timedelta(hours=-5))

    def test_empty_string(self):
        assert parse_hl7_timestamp("") is None

    def test_none(self):
        assert parse_hl7_timestamp(None) is None

    def test_invalid_format(self):
        assert parse_hl7_timestamp("not-a-date") is None

    def test_invalid_date(self):
        assert parse_hl7_timestamp("20261332120000") is None


# ---------------------------------------------------------------------------
# safe_unit
# ---------------------------------------------------------------------------

class TestSafeUnit:
    def test_millivolt(self):
        assert safe_unit("266418^MDC_DIM_MILLI_VOLT^MDC") == "mV"

    def test_hz(self):
        assert safe_unit("264640^MDC_DIM_HZ^MDC") == "Hz"

    def test_dimless(self):
        assert safe_unit("262656^MDC_DIM_DIMLESS^MDC") == "1"

    def test_unknown_unit(self):
        assert safe_unit("123^SOME_UNKNOWN^MDC") == "SOME_UNKNOWN"

    def test_empty(self):
        assert safe_unit("") == ""

    def test_single_component(self):
        assert safe_unit("something") == ""


# ---------------------------------------------------------------------------
# extract_device_id
# ---------------------------------------------------------------------------

class TestExtractDeviceId:
    def test_standard_msh3(self):
        assert extract_device_id("MINDRAY_^00A037000000^EUI-64") == "00A037000000"

    def test_lowercase_hex(self):
        assert extract_device_id("MINDRAY_^00a037000000^EUI-64") == "00A037000000"

    def test_empty(self):
        assert extract_device_id("") == ""

    def test_none(self):
        assert extract_device_id(None) == ""

    def test_no_hex_match(self):
        assert extract_device_id("MINDRAY_^SHORT^EUI-64") == ""


# ---------------------------------------------------------------------------
# parse_obs_id
# ---------------------------------------------------------------------------

class TestParseObsId:
    def test_code_and_name(self):
        code, name = parse_obs_id("131329^MDC_ECG_ELEC_POTL_I^MDC")
        assert code == "131329"
        assert name == "MDC_ECG_ELEC_POTL_I"

    def test_code_only(self):
        code, name = parse_obs_id("131329")
        assert code == "131329"
        assert name == ""

    def test_empty(self):
        code, name = parse_obs_id("")
        assert code == ""
        assert name == ""

    def test_none(self):
        code, name = parse_obs_id(None)
        assert code == ""
        assert name == ""


# ---------------------------------------------------------------------------
# decode_mllp_frames
# ---------------------------------------------------------------------------

class TestDecodeMLLPFrames:
    def test_single_complete_frame(self):
        payload = b"MSH|^~\\&|TEST"
        data = MLLP_START + payload + MLLP_END
        buf = bytearray()
        frames = decode_mllp_frames(data, buf)
        assert len(frames) == 1
        assert frames[0] == payload
        assert len(buf) == 0

    def test_two_frames(self):
        payload1 = b"MSH|^~\\&|MSG1"
        payload2 = b"MSH|^~\\&|MSG2"
        data = MLLP_START + payload1 + MLLP_END + MLLP_START + payload2 + MLLP_END
        buf = bytearray()
        frames = decode_mllp_frames(data, buf)
        assert len(frames) == 2
        assert frames[0] == payload1
        assert frames[1] == payload2

    def test_partial_frame_buffered(self):
        payload = b"MSH|^~\\&|PARTIAL"
        data = MLLP_START + payload  # no end marker
        buf = bytearray()
        frames = decode_mllp_frames(data, buf)
        assert len(frames) == 0
        assert len(buf) > 0

    def test_partial_then_complete(self):
        payload = b"MSH|^~\\&|COMPLETE"
        part1 = MLLP_START + payload[:5]
        part2 = payload[5:] + MLLP_END
        buf = bytearray()
        frames1 = decode_mllp_frames(part1, buf)
        assert len(frames1) == 0
        frames2 = decode_mllp_frames(part2, buf)
        assert len(frames2) == 1
        assert frames2[0] == payload

    def test_empty_data(self):
        buf = bytearray()
        frames = decode_mllp_frames(b"", buf)
        assert len(frames) == 0

    def test_garbage_before_frame(self):
        payload = b"MSH|data"
        data = b"garbage" + MLLP_START + payload + MLLP_END
        buf = bytearray()
        frames = decode_mllp_frames(data, buf)
        assert len(frames) == 1
        assert frames[0] == payload


# ---------------------------------------------------------------------------
# build_ack
# ---------------------------------------------------------------------------

class TestBuildAck:
    def test_ack_structure(self):
        msg = "MSH|^~\\&|MINDRAY_|MINDRAY|||20260124||ORU^R01|1234|P|2.6\rPID|||\r"
        ack = build_ack(msg, "RECV", "RECV")
        assert ack.startswith(MLLP_START)
        assert ack.endswith(MLLP_END)
        inner = ack[1:-2].decode("utf-8")
        segments = inner.split("\r")
        assert segments[0].startswith("MSH|")
        assert "ACK" in segments[0]
        assert segments[1].startswith("MSA|AA|1234")

    def test_ack_swaps_sender(self):
        msg = "MSH|^~\\&|SENDER_APP|SENDER_FAC|||20260124||ORU^R01|99|P|2.6\r"
        ack = build_ack(msg, "MY_APP", "MY_FAC")
        inner = ack[1:-2].decode("utf-8")
        msh = inner.split("\r")[0].split("|")
        assert msh[2] == "MY_APP"
        assert msh[3] == "MY_FAC"
        assert msh[4] == "SENDER_APP"
        assert msh[5] == "SENDER_FAC"


# ---------------------------------------------------------------------------
# process_oru_r01
# ---------------------------------------------------------------------------

class TestProcessOruR01:
    def test_ecg_waveform(self):
        segments = [
            "MSH|^~\\&|MINDRAY_^00A037000000^EUI-64|MINDRAY|||20260124131540000+0800||ORU^R01^ORU_R01|1227|P|2.6",
            "OBR|1||1227^MINDRAY_^00A037000000^EUI-64|100001^CONTINUOUS WAVEFORM^99MNDRY|||20260124131539000+0800|20260124131540000+0800",
            "OBX|1|NA|131329^MDC_ECG_ELEC_POTL_I^MDC|1.7.6.131329|80^88^92",
            "OBX|2|NM|0^MDC_ATTR_SAMP_RATE^MDC|1.7.6.131329.1|500|264640^MDC_DIM_HZ^MDC",
            "OBX|3|NM|2327^MDC_ATTR_NU_MSMT_RES^MDC|1.7.6.131329.2|0.001221|266418^MDC_DIM_MILLI_VOLT^MDC",
        ]
        start, end, channels, numerics = process_oru_r01(segments)
        assert start is not None
        assert end is not None
        assert start < end
        assert len(channels) == 1
        assert len(numerics) == 0
        ch = channels[0]
        assert ch["channel_code"] == "MDC_ECG_ELEC_POTL_I"
        assert ch["sample_rate"] == 500.0
        assert ch["resolution"] == 0.001221
        assert ch["unit"] == "mV"
        assert ch["samples"] == "80^88^92"

    def test_multiple_channels(self):
        segments = [
            "MSH|^~\\&|TEST|||20260124||ORU^R01|1|P|2.6",
            "OBR|1||1|||20260124131539000+0800|20260124131540000+0800",
            "OBX|1|NA|131329^MDC_ECG_ELEC_POTL_I^MDC|1|10^20^30",
            "OBX|2|NM|0^MDC_ATTR_SAMP_RATE^MDC|1.1|500|264640^MDC_DIM_HZ^MDC",
            "OBX|3|NA|150452^MDC_PULS_OXIM_PLETH^MDC|2|100^200",
            "OBX|4|NM|0^MDC_ATTR_SAMP_RATE^MDC|2.1|60|264640^MDC_DIM_HZ^MDC",
        ]
        start, end, channels, _ = process_oru_r01(segments)
        assert len(channels) == 2
        assert channels[0]["channel_code"] == "MDC_ECG_ELEC_POTL_I"
        assert channels[0]["sample_rate"] == 500.0
        assert channels[1]["channel_code"] == "MDC_PULS_OXIM_PLETH"
        assert channels[1]["sample_rate"] == 60.0

    def test_no_obx(self):
        segments = [
            "MSH|^~\\&|TEST|||20260124||ORU^R01|1|P|2.6",
            "OBR|1||1|||20260124131539000+0800|20260124131540000+0800",
        ]
        start, end, channels, _ = process_oru_r01(segments)
        assert start is not None
        assert len(channels) == 0

    def test_inop_flag(self):
        segments = [
            "MSH|^~\\&|TEST|||20260124||ORU^R01|1|P|2.6",
            "OBR|1||1|||20260124131539000+0800|20260124131540000+0800",
            "OBX|1|NA|131329^MDC_ECG_ELEC_POTL_I^MDC|1|10^20",
            "OBX|2|ST|196660^MDC_EVT_INOP^MDC|1.1|32767",
        ]
        _, _, channels, _ = process_oru_r01(segments)
        assert channels[0]["inop"] == "32767"


    def test_numeric_vitals(self):
        segments = [
            "MSH|^~\\&|TEST|||20260124||ORU^R01|1|P|2.6",
            "OBR|1||1|||20260124131539000+0800|20260124131540000+0800",
            "OBX|1|NM|147842^MDC_ECG_HEART_RATE^MDC|1|72|264864^MDC_DIM_BEAT_PER_MIN^MDC",
            "OBX|2|NM|150456^MDC_PULS_OXIM_SAT_O2^MDC|2|98|262688^MDC_DIM_PERCENT^MDC",
        ]
        _, _, channels, numerics = process_oru_r01(segments)
        assert len(channels) == 0
        assert len(numerics) == 2
        assert numerics[0]["name"] == "MDC_ECG_HEART_RATE"
        assert numerics[0]["value"] == 72.0
        assert numerics[1]["name"] == "MDC_PULS_OXIM_SAT_O2"
        assert numerics[1]["value"] == 98.0


# ---------------------------------------------------------------------------
# process_oru_r40
# ---------------------------------------------------------------------------

class TestProcessOruR40:
    def test_alarm_event(self):
        segments = [
            "MSH|^~\\&|MINDRAY_^00A037000000^EUI-64|MINDRAY|||20260124124738000+0800||ORU^R40",
            "OBX|1|CWE|196616^MDC_EVT_ALARM^MDC|1.7.0.196680.1|196680^MDC_EVT_LEAD_OFF^MDC|||A~PL~ST|||R|||20260124124738+0800",
            "OBX|3|ST|68481^MDC_ATTR_EVENT_PHASE^MDC|1.7.0.196680.3|start",
            "OBX|4|ST|68482^MDC_ATTR_ALARM_STATE^MDC|1.7.0.196680.4|active",
            "OBX|6|ST|68484^MDC_ATTR_ALARM_PRIORITY^MDC|1.7.0.196680.6|PL",
        ]
        event = process_oru_r40(segments)
        assert event["event_code"] == "196680"
        assert event["event_name"] == "MDC_EVT_LEAD_OFF"
        assert event["event_phase"] == "start"
        assert event["alarm_state"] == "active"
        assert event["priority"] == "PL"
        assert event["timestamp"] is not None

    def test_empty_segments(self):
        segments = ["MSH|^~\\&|TEST|||20260124||ORU^R40"]
        event = process_oru_r40(segments)
        assert event["event_code"] == ""
        assert event["event_name"] == ""
        assert event["timestamp"] is None
