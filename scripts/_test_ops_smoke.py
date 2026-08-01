# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrate import _parse_review_json  # noqa: E402
from deliver import ops_web  # noqa: E402

raw = "```json\n{\"decision\": \"accept\", \"issues\": [], \"suggestion\": \"ok\"}\n```"
assert _parse_review_json(raw)["decision"] == "accept"
assert _parse_review_json("nonsense") is None
print("parse_ok")
print("ops_port", ops_web._cfg()["port"])
print("ops_enabled", ops_web._cfg()["enabled"])
