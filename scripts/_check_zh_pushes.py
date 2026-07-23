"""检查 GitHub Trending / X Digest 推送是否中文可读。"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _cjk_ratio(s: str) -> float:
    if not s:
        return 0.0
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return cjk / max(len(s), 1)


def check_github() -> dict:
    from deliver.github_trending import fetch_trending, translate_descriptions, format_trending

    repos = fetch_trending()
    before = [r.get("desc", "") for r in repos[:5]]
    translate_descriptions(repos)
    after = [(r.get("name"), r.get("desc", "")) for r in repos[:5]]
    text = format_trending(repos)
    ratios = [_cjk_ratio(d) for _, d in after if d]
    ok = bool(ratios) and sum(1 for r in ratios if r >= 0.25) >= max(1, len(ratios) // 2)
    return {
        "section": "github_trending",
        "n_repos": len(repos),
        "sample_before": before[:2],
        "sample_after": after[:3],
        "avg_cjk_ratio": round(sum(ratios) / len(ratios), 3) if ratios else 0,
        "zh_ok": ok,
        "text_preview": text[:400],
    }


def check_x_digest_archive() -> dict:
    arch = ROOT / "data" / "x_digest" / "archive"
    last = ROOT / "data" / "x_digest" / "last_run.json"
    info = {"section": "x_digest", "last_run": None, "latest_file": None}
    if last.is_file():
        info["last_run"] = json.loads(last.read_text(encoding="utf-8"))
    files = sorted(arch.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True) if arch.is_dir() else []
    if not files:
        info["zh_ok"] = False
        info["error"] = "no archive"
        return info
    f = files[0]
    info["latest_file"] = f.name
    text = f.read_text(encoding="utf-8", errors="replace")
    info["text_preview"] = text[:500]
    info["avg_cjk_ratio"] = round(_cjk_ratio(text), 3)
    # 标题/摘要里应有明显中文
    info["zh_ok"] = _cjk_ratio(text) >= 0.15 and bool(
        re.search(r"[\u4e00-\u9fff]{4,}", text)
    )
    return info


def main() -> int:
    # github 可能因墙失败；失败也报告
    try:
        g = check_github()
    except Exception as e:
        g = {"section": "github_trending", "zh_ok": False, "error": str(e)}
    x = check_x_digest_archive()
    print(json.dumps({"github": g, "x_digest": x}, ensure_ascii=False, indent=2))
    return 0 if g.get("zh_ok") and x.get("zh_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
