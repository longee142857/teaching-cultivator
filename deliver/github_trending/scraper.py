"""GitHub Trending 页面采集 — BeautifulSoup 替代原正则方案。"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TRENDING_URL = "https://github.com/trending?since=daily"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ── 路径常量（相对于项目根） ──
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _detect_proxies() -> dict[str, str] | None:
    """仅给 GitHub 抓取用，勿注入进程全局代理（会弄坏钉钉 Stream）。

    优先级：
      GITHUB_PROXY / TEACHING_GITHUB_PROXY 环境变量
      → 默认云端旁路 socks5h://127.0.0.1:17890（探活失败则直连）
    """
    for key in ("GITHUB_PROXY", "TEACHING_GITHUB_PROXY"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return {"http": val, "https": val}

    default = "socks5h://127.0.0.1:17890"
    try:
        import socket
        with socket.create_connection(("127.0.0.1", 17890), timeout=0.5):
            return {"http": default, "https": default}
    except OSError:
        return None


def _parse_article(article) -> dict | None:
    """解析单个 <article class="Box-row"> 元素。"""
    # owner / name
    h2 = article.select_one("h2")
    if not h2:
        return None
    link = h2.select_one("a")
    if not link:
        return None
    text = link.get_text(strip=True).replace(" ", "")
    if "/" not in text:
        return None
    owner, name = text.split("/", 1)
    full_name = f"{owner}/{name}"

    # description
    p_tag = article.select_one("p")
    desc = p_tag.get_text(strip=True) if p_tag else ""

    # language
    lang_el = article.select_one('[itemprop="programmingLanguage"]')
    lang = lang_el.get_text(strip=True) if lang_el else ""

    # stars (第一个 a.Link--muted)
    star_links = article.select("a.Link--muted")
    stars = ""
    if star_links:
        stars = star_links[0].get_text(strip=True).replace(",", "")

    # built by
    built_by = [
        img.get("alt", "").lstrip("@")
        for img in article.select('img[alt^="@"]')
    ]

    return {
        "name": full_name,
        "desc": desc,
        "lang": lang,
        "stars": stars,
        "built_by": built_by[:3],
        "url": f"https://github.com/{full_name}",
    }


def fetch_trending() -> list[dict]:
    """从 GitHub Trending 页面获取热门项目列表。"""
    proxies = _detect_proxies()
    try:
        resp = requests.get(
            TRENDING_URL,
            headers={"User-Agent": _UA},
            timeout=40,
            proxies=proxies,
        )
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"获取 GitHub Trending 失败: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = soup.select("article.Box-row")

    repos: list[dict] = []
    for art in articles:
        repo = _parse_article(art)
        if repo:
            repos.append(repo)
            if len(repos) >= 15:
                break

    return repos
