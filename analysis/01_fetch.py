"""Step 1: download the pinned VietJobs revision and verify its checksum."""
import hashlib
import sys
import urllib.request
from pathlib import Path

REVISION = "ea140511b77935704e93d21c2973b72f46d48902"
URL = f"https://huggingface.co/datasets/dinhieufam/VietJobs/resolve/{REVISION}/VietJobs.csv"
SHA256 = "85862b06fda4e814fe0c1d8622f173d189c92758345f77df16d1232d0c49d477"
OUT = Path(__file__).resolve().parents[1] / "data/raw/VietJobs.csv"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


if not (OUT.exists() and sha256(OUT) == SHA256):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".part")
    print(f"downloading {URL}")
    urllib.request.urlretrieve(URL, tmp)
    if sha256(tmp) != SHA256:
        tmp.unlink()
        sys.exit("checksum mismatch: upstream file changed")
    tmp.replace(OUT)
print(f"ok {OUT} sha256={SHA256[:12]}")
