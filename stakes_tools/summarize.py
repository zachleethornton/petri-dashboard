#!/usr/bin/env python3
"""Join codes to the keymap and count verdicts, optionally as keep/break.

`verdict` is derived from answer + the bank's yes_means: YES -> yes_means, NO -> the other
of keep/break; OTHER / NONE / CONTRADICTS pass through unchanged.

Examples
  summarize.py --codes C --keymap K                          answer counts per model
  summarize.py --codes C --keymap K --by model,rule,rung --field verdict
  summarize.py --codes C --keymap K --by model,rule --field verdict --csv out.csv
  summarize.py --codes C --keymap K --by model --field misread
"""
import argparse, collections, csv, json, sys
from pathlib import Path


def load(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--codes", required=True)
    p.add_argument("--keymap", required=True)
    p.add_argument("--by", default="model", help="comma-separated keymap/code fields to group by")
    p.add_argument("--field", default="answer", help="code field to count, or 'verdict'")
    p.add_argument("--csv", help="also write the table as CSV")
    a = p.parse_args()

    km = {r["key"]: r for r in load(a.keymap)}
    rows = []
    for c in load(a.codes):
        if c["key"] not in km:
            sys.exit(f"code key {c['key']} not in keymap")
        r = {**km[c["key"]], **c}
        if r.get("model"):
            r["model"] = r["model"].split("/")[-1]
        ym = r.get("yes_means")
        other = {"keep": "break", "break": "keep"}.get(ym)
        r["verdict"] = {"YES": ym, "NO": other}.get(r.get("answer"), r.get("answer"))
        rows.append(r)

    by = [b.strip() for b in a.by.split(",") if b.strip()]
    counts = collections.defaultdict(collections.Counter)
    for r in rows:
        counts[tuple(str(r.get(b)) for b in by)][str(r.get(a.field))] += 1
    values = sorted({v for c in counts.values() for v in c})
    header = by + values + ["n"]
    table = [list(g) + [c.get(v, 0) for v in values] + [sum(c.values())] for g, c in sorted(counts.items())]
    widths = [max(len(str(x)) for x in col) for col in zip(header, *table)]
    for line in [header] + table:
        print("  ".join(str(x).ljust(w) for x, w in zip(line, widths)))
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([header] + table)
        print(f"wrote {a.csv}")


if __name__ == "__main__":
    main()
