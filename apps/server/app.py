import datetime as dt
import hashlib
import os
import shutil
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile


DATA_DIR = os.environ.get("DATA_DIR", "data")
API_KEY = os.environ.get("API_KEY", "")

app = FastAPI(title="Mindray HL7 Ingest", version="0.1.0")


def _check_api_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing API key")
    return x_api_key


def _safe_relative_path(rel_path: str) -> str:
    rel_path = rel_path.replace("\\", "/").strip()
    rel_path = rel_path.lstrip("/")
    norm = os.path.normpath(rel_path)
    if norm.startswith("..") or norm.startswith("/"):
        raise ValueError("invalid relative path")
    return norm


def _bucket_dir(kind: str, now: dt.datetime) -> str:
    return os.path.join(
        DATA_DIR,
        kind,
        now.strftime("%Y"),
        now.strftime("%m"),
        now.strftime("%d"),
        now.strftime("%H"),
    )


@app.get("/health")
def health():
    return {"status": "ok", "time": dt.datetime.now().isoformat()}


@app.post("/upload")
async def upload(
    kind: str = Form(...),
    file: UploadFile = File(...),
    device_id: str = Form(""),
    relative_path: str = Form(""),
    _key: str = Depends(_check_api_key),
):
    now = dt.datetime.now()
    if relative_path:
        try:
            rel = _safe_relative_path(relative_path)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid relative_path")
        dest_path = os.path.join(DATA_DIR, rel)
        dest_dir = os.path.dirname(dest_path)
    else:
        dest_dir = _bucket_dir(kind, now)
        name = file.filename or f"{device_id}_{now.strftime('%Y%m%d_%H%M%S')}.bin"
        dest_path = os.path.join(dest_dir, name)

    os.makedirs(dest_dir, exist_ok=True)

    sha256 = hashlib.sha256()
    size = 0
    with open(dest_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            sha256.update(chunk)
            size += len(chunk)

    return {
        "ok": True,
        "kind": kind,
        "device_id": device_id,
        "path": dest_path,
        "size": size,
        "sha256": sha256.hexdigest(),
    }
