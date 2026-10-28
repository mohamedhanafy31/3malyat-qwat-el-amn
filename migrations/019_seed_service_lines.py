#!/usr/bin/env python3
"""زرع خطوط السير الافتراضية من غير إعادة أي آثار جانبية للهجرة 018."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import AlreadyDone, run  # noqa: E402


LINE_AM, LINE_PM = "08:00", "20:00"
SEED = [
    ("خط فيصل", "فيصل", "LOR-3"),
    ("خط الخارجي (كـ109)", "الخارجي", "LOR-4"),
    ("خط المحور والمحكمة", "المحكمة والمحور", "LOR-1"),
    ("خط الداخلي (القنصلية)", "الداخلي", "LOR-2"),
]


def migrate(data):
    if "019_seed_service_lines" in data.setdefault("_migrations", []):
        raise AlreadyDone("هجرة زرع خطوط السير اتعملت قبل كده.")
    lines = data.setdefault("service_lines", [])
    if lines:
        raise AlreadyDone("خطوط السير موجودة بالفعل — مفيش حاجة تتزرع.")
    lines.extend({"id": f"LN-{i}", "name": name, "tag": tag, "lorry_id": lorry,
                  "order": [], "depart_am": LINE_AM, "depart_pm": LINE_PM}
                 for i, (name, tag, lorry) in enumerate(SEED, 1))
    data["_migrations"].append("019_seed_service_lines")
    return [f"اتزرعت {len(SEED)} خطوط سير افتراضية."]


if __name__ == "__main__":
    run(from_schema=6, to_schema=6, migrate=migrate, title="زرع خطوط السير الافتراضية")
