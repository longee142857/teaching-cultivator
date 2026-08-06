"""GitHub Trending 采集 — 每天推热门项目到钉钉。

向后兼容导出（与旧 import 用法一致）:
    from deliver.github_trending import fetch_trending, translate_descriptions, format_trending

一站式接口:
    from deliver.github_trending import fetch_formatted
    text, n = fetch_formatted()  # 抓取 → 去重 → 翻译 → 格式化
"""
from .scraper import fetch_trending as _fetch
from .translator import translate_descriptions
from .renderer import format_trending
from .cache import TrendingCache
from .sender import send_trending

_cache = TrendingCache()


def fetch_trending() -> list[dict]:
    """抓取 Trending（+ 自动缓存结果到磁盘）。"""
    repos = _fetch()
    if repos:
        _cache.save_cache(repos)
    return repos


def fetch_formatted(
    max_count: int = 10,
    channel: str = "dingtalk",
    use_cache: bool = True,
    skip_dup: bool = True,
) -> tuple[str, int]:
    """一站式：抓取 → 去重 → 翻译 → 格式化。

    Args:
        max_count: 最多显示项目数
        channel: 目标渠道（dingtalk）
        use_cache: 抓取失败时是否用上次缓存
        skip_dup: 是否跳过 7 天内已推过的项目

    Returns:
        (格式化文本, 有效项目数)
    """
    try:
        repos = _fetch()
        if not repos and use_cache:
            cached = _cache.load_cache()
            if cached:
                repos = cached
    except Exception:
        if use_cache:
            cached = _cache.load_cache()
            if cached:
                repos = cached
            else:
                raise
        else:
            raise

    if skip_dup and repos:
        repos = _cache.filter_new(repos)

    if not repos:
        return "", 0

    if repos:
        _cache.save_cache(repos)

    translate_descriptions(repos)
    text = format_trending(repos, max_count=max_count, channel=channel)
    return text, len(repos)


__all__ = [
    "fetch_trending",
    "translate_descriptions",
    "format_trending",
    "fetch_formatted",
    "TrendingCache",
    "send_trending",
]
