"""One-shot health check for 2026-07-15 session log."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    ok = True
    for unit in ("teaching-cultivator", "cloud-proxy"):
        r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
        status = (r.stdout or "").strip()
        print(f"service {unit}: {status}")
        ok = ok and status == "active"

    from deliver.github_trending import fetch_trending, translate_descriptions, _requests_proxies

    print("proxies", _requests_proxies())
    repos = fetch_trending()
    translate_descriptions(repos)
    zh = repos[0].get("desc") or ""
    cjk = sum(1 for ch in zh if "\u4e00" <= ch <= "\u9fff") / max(len(zh), 1)
    print(f"github repos={len(repos)} zh_sample={zh[:40]!r} cjk={cjk:.3f}")
    ok = ok and len(repos) >= 5 and cjk >= 0.2

    from deliver.x_digest import XDigest

    skip = XDigest()._already_ran_today()
    print("x_already_today", skip)
    ok = ok and (not skip)

    from learner.weights_ops import load_weights

    w = load_weights()
    nm, nc = len(w["math"]["kp_weights"]), len(w["comm"]["kp_weights"])
    print(f"kp_weights math={nm} comm={nc}")
    ok = ok and nm == 30 and nc == 30

    env = load_env(ROOT / ".env")
    r = requests.post(
        "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        json={
            "appKey": env["DINGTALK_CLIENT_ID"],
            "appSecret": env["DINGTALK_CLIENT_SECRET"],
        },
        timeout=15,
    )
    token = r.json().get("accessToken", "")
    print("token_ok", bool(token))
    ok = ok and bool(token)

    jr = subprocess.run(
        ["journalctl", "-u", "teaching-cultivator", "-n", "30", "--no-pager"],
        capture_output=True,
        text=True,
    )
    out = jr.stdout or ""
    print("stream_endpoint", "endpoint is" in out)
    print("stream_recent_fail", "open connection failed" in out.split("Started teaching-cultivator")[-1])

    print("OVERALL", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
