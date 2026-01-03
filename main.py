from fastapi import FastAPI
from pydantic import BaseModel
import subprocess, tempfile, requests
from pathlib import Path

app = FastAPI()

class Req(BaseModel):
    url1: str
    url2: str

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stdout)

def download(url, out):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for c in r.iter_content(1024*1024):
                if c:
                    f.write(c)

@app.post("/merge")
def merge(req: Req):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        v1, v2 = td/"1.mp4", td/"2.mp4"
        out = td/"out.mp4"
        lst = td/"list.txt"

        download(req.url1, v1)
        download(req.url2, v2)

        lst.write_text(f"file '{v1}'\nfile '{v2}'\n")

        run([
            "ffmpeg","-y","-f","concat","-safe","0",
            "-i",str(lst),"-c","copy",str(out)
        ])

        return {"status": "ok", "size_bytes": out.stat().st_size}

