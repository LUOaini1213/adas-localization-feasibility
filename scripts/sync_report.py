"""Copy generated tables from results/tables.md into report.md.

report.md contains blocks
    <!-- AUTO:表 6 -->
    ...
    <!-- /AUTO -->
whose content is replaced by the body of the section "## 表 6 ..." of results/tables.md (heading line
excluded).  The prose of report.md is never touched, so numbers in the tables cannot drift from the
script outputs.

Run (after make_tables.py):  python -X utf8 -B -I scripts/sync_report.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sections(tables: str) -> dict[str, str]:
    out, key, buf = {}, None, []
    for line in tables.splitlines():
        m = re.match(r"^## (表 \d+)\s", line)
        if m:
            if key:
                out[key] = "\n".join(buf).strip()
            key, buf = m.group(1), []
        elif key:
            buf.append(line)
    if key:
        out[key] = "\n".join(buf).strip()
    return out


def synchronise(text: str, secs: dict[str, str]) -> tuple[str, int]:
    """Return the report text with every AUTO block replaced by its tables.md section, and the block count."""
    n = 0

    def rep(m):
        nonlocal n
        key = m.group(1)
        if key not in secs:
            raise KeyError(f"report.md asks for {key}, not found in results/tables.md")
        n += 1
        return f"<!-- AUTO:{key} -->\n{secs[key]}\n<!-- /AUTO -->"

    return re.sub(r"<!-- AUTO:(表 \d+) -->.*?<!-- /AUTO -->", rep, text, flags=re.S), n


def main() -> int:
    secs = sections((ROOT / "results" / "tables.md").read_text(encoding="utf-8"))
    path = ROOT / "report.md"
    if not path.exists():
        print("report.md not found - nothing to synchronise")
        return 0
    new, n = synchronise(path.read_text(encoding="utf-8"), secs)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    print(f"report.md: {n} blocks synchronised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
