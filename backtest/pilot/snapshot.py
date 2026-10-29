#!/usr/bin/env python3
"""
Unpack the snapshot zip made on the PC (fetch.py --pack) into a new empty folder, in the cloud, after checking
it: the zip's md5 against the value printed on the PC, every member name against the snapshot's layout (no
absolute paths, no "..", no other files), then every file against the manifest (market.check_manifest) and the
manifest's md5 against the PC's value. The data are only ever read with json.

    python3 -I -B backtest/pilot/snapshot.py --zip FILE --zip-md5 HEX --manifest-md5 HEX --out NEW_DIR
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import market as M  # noqa: E402

TOP = {"manifest.json", "run.json", "fetch_log.json", "status.json"}
PARTS = {"full", "adj", "inc_q", "inc_a", "splits", "div", "earn", "profile", "est", "light", "mcap", "market"}
NAME = re.compile(r"^raw/([a-z_]+)/([A-Za-z0-9][A-Za-z0-9._-]{0,40})\.json$")


def allowed(name: str) -> bool:
    if name in TOP:
        return True
    m = NAME.match(name)
    return bool(m) and m.group(1) in PARTS and ".." not in name


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--zip", required=True)
    ap.add_argument("--zip-md5", required=True)
    ap.add_argument("--manifest-md5", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    zp, out = Path(a.zip), Path(a.out)
    if md5(zp.read_bytes()) != a.zip_md5.lower():
        print("refused: the zip's md5 differs from the PC's value")
        return 2
    if out.exists() and any(out.iterdir()):
        print("refused: the output folder is not empty")
        return 2
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        bad = [n for n in names if not allowed(n)]
        if bad or "manifest.json" not in names:
            print(f"refused: {len(bad)} unexpected member names, e.g. {bad[:3]}" if bad else "refused: no manifest")
            return 2
        out.mkdir(parents=True, exist_ok=True)
        for n in names:
            dest = out / n
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(n))
    if md5((out / "manifest.json").read_bytes()) != a.manifest_md5.lower():
        print("refused: the manifest's md5 differs from the PC's value")
        return 2
    diff = M.check_manifest(out)
    if diff:
        print(f"refused: {len(diff)} files differ from the manifest, e.g. {diff[:3]}")
        return 2
    print(f"ok: {len(names)} files in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
