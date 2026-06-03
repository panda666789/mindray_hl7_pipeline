#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${PROJECT_ROOT}/docs/sample_data"

RAW_DIR="/opt/mindray_hl7_pipeline/data/raw_hl7"
WAVE_DIR="/opt/mindray_hl7_pipeline/data/waveform_csv"
EVENT_DIR="/opt/mindray_hl7_pipeline/data/events_csv"

mkdir -p "${OUT_DIR}"

latest_file() {
  local dir="$1"
  find "$dir" -type f -name "*.gz" -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n1 | cut -d' ' -f2-
}

RAW_FILE="$(latest_file "$RAW_DIR" || true)"
WAVE_FILE="$(latest_file "$WAVE_DIR" || true)"
EVENT_FILE="$(latest_file "$EVENT_DIR" || true)"

if [[ -n "${RAW_FILE}" ]]; then
  zcat "${RAW_FILE}" | tr '\r' '\n' | head -n 50 > "${OUT_DIR}/raw_hl7_sample.hl7"
  echo "Wrote: ${OUT_DIR}/raw_hl7_sample.hl7"
else
  echo "No raw_hl7 data found under ${RAW_DIR}"
fi

if [[ -n "${WAVE_FILE}" ]]; then
  zcat "${WAVE_FILE}" | head -n 3 > "${OUT_DIR}/waveform_sample.csv"
  echo "Wrote: ${OUT_DIR}/waveform_sample.csv"
else
  echo "No waveform_csv data found under ${WAVE_DIR}"
fi

if [[ -n "${EVENT_FILE}" ]]; then
  zcat "${EVENT_FILE}" | head -n 3 > "${OUT_DIR}/events_sample.csv"
  echo "Wrote: ${OUT_DIR}/events_sample.csv"
else
  echo "No events_csv data found under ${EVENT_DIR}"
fi
