#!/usr/bin/env python3
"""Validate coder output, set aside bad batches, list what to run next, and merge.

The schema is read from the rubric's Output section: the line that starts with
{"key": ...}. A value written "A|B|C" is an enum, true|false is a boolean, "..." is any
string. So a v3 rubric with new fields needs no code change.

Each <out-dir>/batch_NNN.md must have a batch_NNN.codes.jsonl beside it with exactly one
valid object per key of that batch.

Usage
  check_codes.py --dir D --rubric R                       status per batch + summary
  check_codes.py --dir D --rubric R --set-aside           move invalid outputs to D/rejected/
                                                          (logged in D/rejected/log.txt)
  check_codes.py --dir D --rubric R --next 15 [--print-prompts]
                                                          list (and print prompts for) the next
                                                          batches still to run
  check_codes.py --dir D --rubric R --merge CODES --keymap KEYMAP [--keymap-out PATH]
                                                          write all codes; exit 2 unless every
                                                          keymap key is coded exactly once
"""
import argparse, json, re, shutil, sys
from pathlib import Path


def rubric_schema(path):
    text = Path(path).read_text(encoding="utf-8")
    line = next((l.strip() for l in text.splitlines() if l.strip().startswith('{"key"')), None)
    if not line:
        sys.exit(f"{path}: no Output line starting with {{\"key\" found")
    schema = {}
    for m in re.finditer(r'"(\w+)"\s*:\s*(?:"([^"]*)"|([A-Za-z|]+))', line):
        name, quoted, bare = m.group(1), m.group(2), m.group(3)
        if name == "key":
            continue
        if bare is not None:
            vals = set(bare.split("|"))
            if vals <= {"true", "false"}:
                schema[name] = ("bool", None)
            else:
                schema[name] = ("enum", vals)
        elif quoted is not None and "|" in quoted:
            schema[name] = ("enum", set(quoted.split("|")))
        else:
            schema[name] = ("str", None)
    if not schema:
        sys.exit(f"{path}: could not parse any fields from: {line}")
    return schema


def check(path, keys, schema):
    if not path.exists():
        return None, "missing"
    fields = ["key"] + list(schema)
    out = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError as e:
            return None, f"line {n} is not JSON ({e.msg})"
        if not isinstance(o, dict) or sorted(o) != sorted(fields):
            return None, f"line {n} has fields {sorted(o) if isinstance(o, dict) else type(o).__name__}"
        for f, (kind, vals) in schema.items():
            v = o[f]
            if kind == "bool" and not isinstance(v, bool):
                return None, f"line {n}: {f}={v!r} is not a boolean"
            if kind == "enum" and v not in vals:
                return None, f"line {n}: {f}={v!r} not in {sorted(vals)}"
            if kind == "str" and not isinstance(v, str):
                return None, f"line {n}: {f}={v!r} is not a string"
        if o["key"] in out:
            return None, f"key {o['key']} coded twice"
        out[o["key"]] = {k: o[k] for k in fields}
    miss, extra = set(keys) - set(out), set(out) - set(keys)
    if miss or extra:
        return None, f"{len(miss)} keys missing, {len(extra)} unknown keys"
    return [out[k] for k in keys], "ok"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", required=True)
    p.add_argument("--rubric", required=True)
    p.add_argument("--set-aside", action="store_true")
    p.add_argument("--next", type=int, default=0)
    p.add_argument("--print-prompts", action="store_true")
    p.add_argument("--merge")
    p.add_argument("--keymap")
    p.add_argument("--keymap-out")
    a = p.parse_args()

    d = Path(a.dir)
    batches = json.loads((d / "batches.json").read_text(encoding="utf-8"))
    schema = rubric_schema(a.rubric)
    merged, todo, bad = [], [], []
    for b, keys in batches.items():
        rows, status = check(d / f"batch_{b}.codes.jsonl", keys, schema)
        if rows is None:
            todo.append(b)
            if status != "missing":
                bad.append((b, status))
        else:
            merged += rows
    for b, status in bad:
        print(f"batch {b}: invalid: {status}")
        if a.set_aside:
            rej = d / "rejected"
            rej.mkdir(exist_ok=True)
            n = 1
            while (rej / f"batch_{b}.codes.try{n}.jsonl").exists():
                n += 1
            shutil.move(str(d / f"batch_{b}.codes.jsonl"), str(rej / f"batch_{b}.codes.try{n}.jsonl"))
            with open(rej / "log.txt", "a", encoding="utf-8") as f:
                f.write(f"{b} try{n}: {status}\n")
            print(f"  set aside as rejected/batch_{b}.codes.try{n}.jsonl")
    print(f"{len(batches) - len(todo)}/{len(batches)} batches valid ({len(merged)} keys coded); "
          f"{len(todo)} to run")

    if a.next:
        nxt = todo[:a.next]
        print("NEXT: " + (" ".join(nxt) if nxt else "none"))
        if a.print_prompts and nxt:
            prompts = {json.loads(l)["batch"]: json.loads(l)["prompt"]
                       for l in (d / "coder_prompts.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
            for b in nxt:
                print(f"\n===== PROMPT batch {b} =====\n{prompts[b]}")

    if a.merge:
        if not a.keymap:
            sys.exit("--merge needs --keymap")
        km = [json.loads(l) for l in Path(a.keymap).read_text(encoding="utf-8").splitlines() if l.strip()]
        km_keys = [r["key"] for r in km]
        coded = [r["key"] for r in merged]
        problems = []
        if todo:
            problems.append(f"{len(todo)} batches not validly coded: {' '.join(todo[:20])}")
        if len(set(km_keys)) != len(km_keys):
            problems.append("keymap has duplicate keys")
        if len(set(coded)) != len(coded):
            problems.append("a key is coded in more than one batch")
        if set(coded) != set(km_keys):
            problems.append(f"coded keys != keymap keys ({len(set(km_keys) - set(coded))} uncoded, "
                            f"{len(set(coded) - set(km_keys))} unknown)")
        if problems:
            print("MERGE FAILED:\n  " + "\n  ".join(problems), file=sys.stderr)
            sys.exit(2)
        Path(a.merge).write_text("".join(json.dumps(r) + "\n" for r in merged), encoding="utf-8")
        print(f"MERGED {len(merged)} codes -> {a.merge} (every keymap key coded exactly once)")
        if a.keymap_out:
            shutil.copyfile(a.keymap, a.keymap_out)
            print(f"keymap -> {a.keymap_out}")


if __name__ == "__main__":
    main()
