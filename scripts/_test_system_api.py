"""system_api 白名单冒烟（不启 HTTP：直接 call_tool；临时 DATA_DIR）。"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config as config_mod  # noqa: E402
from deliver.system_api import WHITELIST, call_tool  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        with patch.object(config_mod, "DATA_DIR", td):
            assert "get_active_question" in WHITELIST
            assert "grade_answer" in WHITELIST
            assert "list_today_questions" in WHITELIST
            assert "github_push" not in WHITELIST
            lid = os.environ.get("OWNER_STAFF_ID") or os.environ.get("LEARNER_USER_ID") or "test_api_user"
            r = call_tool("get_active_question", lid, {})
            assert r.get("ok") is True, r
            assert "result" in r
            r2 = call_tool("list_today_questions", lid, {})
            assert r2.get("ok") is True, r2
            assert "result" in r2
            bad = call_tool("github_push", lid, {})
            assert bad.get("ok") is False
    print("PASS system_api whitelist + get_active_question + list_today_questions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
