"""GitHub Trending 采集 — 每天10个热门项目推钉钉"""
from __future__ import annotations
import json
import os
import re

TRENDING_URL = "https://github.com/trending?since=daily"
_UA = "Mozilla/5.0 (compatible; teaching-cultivator/1.0)"


def _requests_proxies() -> dict[str, str] | None:
    """仅给 GitHub 抓取用，勿注入进程全局代理（会弄坏钉钉 Stream）。

    优先级：
      GITHUB_PROXY / TEACHING_GITHUB_PROXY
      → 默认云端旁路 socks5h://127.0.0.1:17890（探活失败则直连）
    """
    for key in ("GITHUB_PROXY", "TEACHING_GITHUB_PROXY"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return {"http": val, "https": val}

    default = "socks5h://127.0.0.1:17890"
    # 旁路没起来时不要硬绑，避免误报 SOCKS 依赖错误掩盖直连结果
    try:
        import socket
        host, port_s = "127.0.0.1", "17890"
        with socket.create_connection((host, int(port_s)), timeout=0.5):
            return {"http": default, "https": default}
    except OSError:
        return None


def fetch_trending() -> list[dict]:
    """GitHub Trending 页面 → repo 列表"""
    import requests
    proxies = _requests_proxies()
    try:
        resp = requests.get(
            TRENDING_URL,
            headers={"User-Agent": _UA},
            timeout=40,
            proxies=proxies,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        raise RuntimeError(f"获取 GitHub Trending 失败: {e}")

    repos = []
    articles = re.findall(
        r'<article\s+class="Box-row"[^>]*>(.*?)</article>', html, re.DOTALL
    )

    for a in articles:
        # owner / name
        m = re.search(
            r'<span[^>]*class="text-normal"[^>]*>([^<]+)</span>\s*([^<]+)', a
        )
        if not m:
            continue
        owner = m.group(1).strip().rstrip("/ ")
        name = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        full_name = f"{owner}/{name}"

        # description
        desc_m = re.search(
            r'<p[^>]*class="col-9[^"]*"[^>]*>([\s\S]*?)</p>', a
        )
        desc = ""
        if desc_m:
            desc = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip()
            desc = re.sub(r"\s+", " ", desc)

        # language
        lang_m = re.search(
            r'itemprop="programmingLanguage"[^>]*>([^<]+)', a
        )
        lang = lang_m.group(1).strip() if lang_m else ""

        # stars
        stars_m = re.search(
            r'stargazers"[^>]*>.*?([\d,]+)\s*</a>', a, re.DOTALL
        )
        stars = stars_m.group(1) if stars_m else ""

        # built by
        built_by = re.findall(r'alt="@([^"]+)"', a)

        repos.append({
            "name": full_name,
            "desc": desc,
            "lang": lang,
            "stars": stars,
            "built_by": built_by[:3],
            "url": f"https://github.com/{full_name}",
        })

        if len(repos) >= 15:
            break

    return repos


def translate_descriptions(repos: list[dict]) -> list[dict]:
    """批量翻译 desc 到中文（一次性 LLM 调用）。"""
    need = [(i, r["desc"]) for i, r in enumerate(repos) if r.get("desc")]
    if not need:
        return repos

    from config import DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, MODEL_FLASH
    import requests

    items = "\n".join(f"{i}. {desc}" for i, desc in (need))
    prompt = (
        "将以下 GitHub 项目描述翻译成简洁的中文。只翻译，不添加额外信息。"
        "返回纯 JSON 数组，每项格式为 {\"idx\": 序号, \"zh\": \"翻译结果\"}。\n\n"
        + items
    )

    try:
        resp = requests.post(
            f"{DEEPSEEK_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            json={
                "model": MODEL_FLASH,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 2000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # 提取 JSON（模型可能用 ```json 包裹）
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        translations = json.loads(content)
        mapping = {t["idx"]: t["zh"] for t in translations}
        for i, r in enumerate(repos):
            if i in mapping:
                r["desc"] = mapping[i]
    except Exception as e:
        # 翻译失败不回退，保留英文
        print(f"[translate] 翻译失败: {e}")

    return repos


def format_trending(repos: list[dict], max_count: int = 10) -> str:
    """repo 列表 → 钉钉 markdown 文本"""
    lines = ["## 🔥 GitHub 今日热门\n"]
    for i, r in enumerate(repos[:max_count], 1):
        name = r["name"]
        desc = r["desc"]
        lang = r["lang"]
        stars = r["stars"]
        url = r["url"]
        built = r["built_by"]

        line = f"**{i}. [{name}]({url})**"
        if stars:
            line += f"  ⭐ {stars}"
        lines.append(line)
        if desc:
            lines.append(f"   {desc}")
        meta = "  ".join(filter(None, [lang, f"开发者 @{', @'.join(built)}" if built else ""]))
        if meta:
            lines.append(f"   {meta}")
        lines.append("")

    return "\n".join(lines)
