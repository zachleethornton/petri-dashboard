"""Validate coder output for the stakes v2 battery and merge valid batches.

Each batch_NNN.md in <batch_dir> should have a batch_NNN.codes.jsonl beside it with exactly
one valid JSON object per key of that batch (see classify_rubric.md for the schema).

Usage: python check_codes.py <batch_dir> [--merge <codes.jsonl>]
Prints one status per batch (ok / missing / invalid: reason) and a summary line listing the
batches that still need (re-)running.
"""
import json, sys
from pathlib import Path

batch_dir = Path(sys.argv[1])
merge_to = Path(sys.argv[sys.argv.index("--merge") + 1]) if "--merge" in sys.argv else None
batches = json.loads((batch_dir / "batches.json").read_text(encoding="utf-8"))

FIELDS = ["key", "answer", "first_word_conflict", "misread", "reason"]
ANSWERS = {"YES", "NO", "OTHER", "NONE", "CONTRADICTS"}
REASONS = {"CONSEQUENCES", "DUTIES", "BOTH", "NEITHER"}


def check(b, keys):
    f = batch_dir / f"batch_{b}.codes.jsonl"
    if not f.exists():
        return None, "missing"
    out = {}
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError as e:
            return None, f"line {n} is not JSON ({e.msg})"
        if sorted(o) != sorted(FIELDS):
            return None, f"line {n} has fields {sorted(o)}"
        if o["answer"] not in ANSWERS or o["reason"] not in REASONS:
            return None, f"line {n} has a bad value: {o['answer']}/{o['reason']}"
        if not isinstance(o["first_word_conflict"], bool) or not isinstance(o["misread"], bool):
            return None, f"line {n} has a non-boolean flag"
        if o["key"] in out:
            return None, f"key {o['key']} coded twice"
        out[o["key"]] = {k: o[k] for k in FIELDS}
    if set(out) != set(keys):
        return None, f"{len(set(keys) - set(out))} keys missing, {len(set(out) - set(keys))} unknown keys"
    return [out[k] for k in keys], "ok"


todo, merged = [], []
for b, keys in batches.items():
    rows, status = check(b, keys)
    if rows is None:
        todo.append(b)
        if status != "missing":
            print(f"batch {b}: invalid: {status}")
    else:
        merged += rows

print(f"{len(batches) - len(todo)}/{len(batches)} batches valid ({len(merged)} keys coded); "
      f"to run: {' '.join(todo) if todo else 'none'}")
if merge_to:
    merge_to.write_text("".join(json.dumps(r) + "\n" for r in merged), encoding="utf-8")
    print(f"wrote {len(merged)} codes to {merge_to}")
