from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
import subprocess, tempfile, requests, uuid, os, time
from pathlib import Path

app = FastAPI()

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "storage")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FILES_PREFIX = os.getenv("FILES_PREFIX", "/files")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

app.mount(FILES_PREFIX, StaticFiles(directory=str(OUTPUT_DIR)), name="files")

class Req(BaseModel):
    url1: HttpUrl
    url2: HttpUrl

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stdout)

def download(url, out, max_bytes=500*1024*1024):
    total = 0
    with requests.get(url, stream=True, timeout=(10, 120)) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for c in r.iter_content(1024*1024):
                if not c:
                    continue
                total += len(c)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail="File too large")
                f.write(c)

def build_public_url(request: Request, rel_path: str) -> str:
    if BASE_URL:
        return f"{BASE_URL}{rel_path}"
    return str(request.base_url).rstrip("/") + rel_path

def delete_later(path: Path, delay_seconds: int):
    time.sleep(delay_seconds)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass

def cleanup_old_files(dir_path: Path, max_age_seconds: int = 120):
    now = time.time()
    for p in dir_path.glob("*.mp4"):
        try:
            if now - p.stat().st_mtime > max_age_seconds:
                p.unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/merge")
def merge(req: Req, request: Request, background: BackgroundTasks):
    cleanup_old_files(OUTPUT_DIR, 120)
    out_name = f"{uuid.uuid4().hex}.mp4"
    out_path = OUTPUT_DIR / out_name

    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            v1, v2 = td/"1.mp4", td/"2.mp4"
            lst = td/"list.txt"

            download(str(req.url1), v1)
            download(str(req.url2), v2)

            lst.write_text(f"file '{v1}'\nfile '{v2}'\n", encoding="utf-8")

            run([
                "ffmpeg","-y","-hide_banner","-loglevel","error",
                "-f","concat","-safe","0",
                "-i",str(lst),
                "-c","copy",
                str(out_path)
            ])

        rel_url = f"{FILES_PREFIX}/{out_name}"
        url = build_public_url(request, rel_url)

        # удалить файл через 60 секунд
        background.add_task(delete_later, out_path, 60)

        return {"status": "ok", "url": url, "expires_in_seconds": 60, "size_bytes": out_path.stat().st_size}

    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Download failed: {e}")
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=f"FFmpeg failed: {str(e)[:2000]}")
