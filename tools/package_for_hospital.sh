#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${PROJECT_ROOT}/dist"
STAMP="$(date +%Y%m%d_%H%M%S)"
PACKAGE="${OUT_DIR}/mindray_hl7_pipeline_hospital_${STAMP}.zip"

mkdir -p "${OUT_DIR}"

PACKAGE_PATH="${PACKAGE}" PROJECT_ROOT="${PROJECT_ROOT}" python3 - <<'PY'
import os
import zipfile
from pathlib import Path

project_root = Path(os.environ["PROJECT_ROOT"]).resolve()
package_path = Path(os.environ["PACKAGE_PATH"]).resolve()
root_name = project_root.name

excluded_dirs = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "data",
    "logs",
    "dist",
}
excluded_files = {".DS_Store"}

def should_exclude(path: Path) -> bool:
    rel = path.relative_to(project_root)
    parts = rel.parts
    if any(part in excluded_dirs for part in parts):
        return True
    if path.name in excluded_files or path.suffix == ".pyc":
        return True
    if len(parts) >= 2 and parts[0] == "docs" and parts[1] == "sample_data":
        return True
    return False

with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(project_root.rglob("*")):
        if should_exclude(path) or path.is_dir():
            continue
        arcname = Path(root_name) / path.relative_to(project_root)
        zf.write(path, arcname)
PY

echo "Wrote: ${PACKAGE}"
echo "Excluded: .git .venv data logs dist __pycache__ .pytest_cache docs/sample_data"
