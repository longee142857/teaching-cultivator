"""GitHub Trending 项目描述翻译 — LLM 批量翻译。"""
from __future__ import annotations

import json
import logging
import os
import re

import requests

logger = logging.getLogger(__name__)


def translate_descriptions(repos: list[dict]) -> list[dict]:
    """批量翻译 repo 描述到中文（DeepSeek Flash），入参原地修改也返回。"""
    need = [(i, r["desc"]) for i, r in enumerate(repos) if r.get("desc")]
    if not need:
        return repos

    api_key = _get_config("DEEPSEEK_API_KEY")
    api_base = _get_config("DEEPSEEK_API_BASE") or "https://api.deepseek.com"
    model = _get_config("MODEL_FLASH") or "deepseek-chat"

    if not api_key:
        logger.warning("[translate] DEEPSEEK_API_KEY 未配置，跳过翻译")
        return repos

    items = "\n".join(f"{i}. {desc}" for i, desc in need)
    prompt = (
        "将以下 GitHub 项目描述翻译成简洁的中文。只翻译，不添加额外信息。"
        "返回纯 JSON 数组，每项格式为 {\"idx\": 序号, \"zh\": \"翻译结果\"}。\n\n"
        + items
    )

    try:
        resp = requests.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 2000,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]

        # 提取 JSON（模型有时用 ```json 包裹）
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        translations = json.loads(content)
        mapping = {t["idx"]: t["zh"] for t in translations}
        for i, r in enumerate(repos):
            if i in mapping:
                r["desc"] = mapping[i]
        logger.info(f"[translate] 成功翻译 {len(mapping)} 条描述")
    except Exception as e:
        logger.warning(f"[translate] 翻译失败，保留英文: {e}")

    return repos


def _get_config(key: str) -> str | None:
    """从多种来源读取配置，优先级：os.environ > sys.modules['config'] > config 硬导入。"""
    # 1. os.environ（config.py 的 _load_dotenv 已注入）
    val = os.environ.get(key)
    if val:
        return val

    # 2. sys.modules（main.py 已导入 config）
    try:
        import sys
        if "config" in sys.modules:
            val = getattr(sys.modules["config"], key, None)
            if val:
                return val
    except Exception:
        pass

    # 3. 硬导入（兜底）
    try:
        import importlib
        cfg = importlib.import_module("config")
        return getattr(cfg, key, None) or None
    except Exception:
        return None
