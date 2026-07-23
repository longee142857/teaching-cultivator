"""Clear last_run so scheduled Wed/Sat 21:00 is not skipped after a manual morning run."""
import json
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "data" / "x_digest" / "last_run.json"
bak = p.with_name("last_run.manual-0943.bak.json")
if p.is_file():
    bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
p.write_text(
    json.dumps(
        {
            "date": "1970-01-01",
            "at": "cleared",
            "note": "09:43 archive kept; not the Wed/Sat 21:00 slot",
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
print("cleared", p)
print(p.read_text(encoding="utf-8"))
