#!/usr/bin/env python3
"""Blind, shuffle and batch battery replies for coding by fresh Claude subagents.

For every reply: assign a random key, strip bracketed article citations ([8.3], [1.2,1.4],
[2.1][5.2], [8.2]-[8.6]; NOT expected-value brackets like [-6 at .9]), shuffle everything,
and cut into batches. A coder sees only: the rubric, and per item the KEY, the SCENARIO
(the full prompt the model received, joined from the bank by id), the QUESTION and the
cleaned REPLY. No model names, ids, case labels or factor columns.

Writes
  <keymap>                          key -> every reply/bank field except the reply text
                                    (id, model, sample, finish_reason, case, rule, ...,
                                    extra factor columns), shuffled order. Never show coders.
  <out-dir>/batch_NNN.md            rubric + items, nothing else
  <out-dir>/batches.json            batch number -> keys (used by check_codes.py)
  <out-dir>/coder_prompts.jsonl     {"batch", "n", "prompt"}: the exact text to give one fresh
                                    general-purpose subagent per batch (from coder_prompt.md)

Example:
  python3 -I prepare_coding.py --replies out/stakes_v3_replies.jsonl \
      --bank banks/stakes_bank_v3.jsonl --rubric rubrics/classify_rubric_v3.md \
      --out-dir out/stakes_v3_coding --keymap out/stakes_v3_keymap.jsonl --batch-size 100
"""
import argparse, json, random, re, secrets, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# One citation: [3.3], [8.5], [1.2,1.4], [1.2, 1.4], [8.2-8.6]. A run of them, adjacent
# ("[2.1][5.2]") or dash-joined ("[8.2]-[8.6]"), is removed as a unit.
CIT = r"\[\s*\d+(?:\.\d+)*(?:\s*[,;–—-]\s*\d+(?:\.\d+)*)*\s*\]"
RUN = re.compile(rf"[ \t]*{CIT}(?:\s*[–—-]?\s*{CIT})*")


def clean(text):
    out = RUN.sub("", text)
    out = re.sub(r"[ \t]+([.,;:!?)])(?!\d)", r"\1", out)  # no space before punctuation (keeps " .8")
    out = re.sub(r"\(\s*\)", "", out)                      # "( )" left by "([3.3])"
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--replies", required=True)
    p.add_argument("--bank", required=True, help="the bank the replies were generated from (for SCENARIO)")
    p.add_argument("--rubric", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--keymap", required=True)
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--prompt-template", default=str(HERE / "coder_prompt.md"))
    p.add_argument("--seed", type=int, help="shuffle seed (default: system randomness)")
    a = p.parse_args()

    out_dir, keymap = Path(a.out_dir), Path(a.keymap)
    if out_dir.exists() and any(out_dir.glob("batch_*")):
        sys.exit(f"{out_dir} already has batches; refusing to overwrite (keys would change)")
    bank = {}
    for l in Path(a.bank).read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            bank[r["id"]] = r
    rows = [json.loads(l) for l in Path(a.replies).read_text(encoding="utf-8").splitlines() if l.strip()]
    missing = sorted({r["id"] for r in rows} - set(bank))
    if missing:
        sys.exit(f"{len(missing)} reply ids are not in the bank, e.g. {missing[:3]}")
    rubric = Path(a.rubric).read_text(encoding="utf-8").strip()
    template = Path(a.prompt_template).read_text(encoding="utf-8")

    keys, items = set(), []
    for r in rows:
        k = "k" + secrets.token_hex(5)
        while k in keys:
            k = "k" + secrets.token_hex(5)
        keys.add(k)
        meta = {"key": k, **{f: v for f, v in r.items() if f != "reply"}}
        items.append({"meta": meta, "scenario": bank[r["id"]]["prompt"],
                      "question": r["question"], "reply": clean(r["reply"])})
    (random.Random(a.seed) if a.seed is not None else random.SystemRandom()).shuffle(items)

    keymap.parent.mkdir(parents=True, exist_ok=True)
    keymap.write_text("".join(json.dumps(it["meta"], ensure_ascii=False) + "\n" for it in items),
                      encoding="utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    models = {it["meta"].get("model", "") for it in items} - {""}
    ids = {it["meta"]["id"] for it in items}
    batches, prompts = {}, []
    for b, start in enumerate(range(0, len(items), a.batch_size), 1):
        chunk = items[start:start + a.batch_size]
        bn = f"{b:03d}"
        batches[bn] = [it["meta"]["key"] for it in chunk]
        parts = [rubric, "", "## Items", "",
                 "Each item has a KEY, the SCENARIO (the user's full message to the model), the "
                 "QUESTION it ends with, and the model's REPLY.", ""]
        for it in chunk:
            parts += [f"### KEY: {it['meta']['key']}", "", "SCENARIO:", "", it["scenario"], "",
                      f"QUESTION: {it['question']}", "", "REPLY:", "", it["reply"], "", "---", ""]
        text = "\n".join(parts)
        leaks = [s for s in models | ids if s and s in text]
        if leaks:
            sys.exit(f"batch {bn} would leak {leaks[:3]} to the coder; aborting")
        bfile = (out_dir / f"batch_{bn}.md").resolve()
        bfile.write_text(text, encoding="utf-8")
        prompts.append({"batch": bn, "n": len(chunk), "prompt": template
                        .replace("{BATCH_FILE}", str(bfile))
                        .replace("{CODES_FILE}", str(bfile.with_name(f"batch_{bn}.codes.jsonl")))
                        .replace("{N}", str(len(chunk)))})
    (out_dir / "batches.json").write_text(json.dumps(batches), encoding="utf-8")
    (out_dir / "coder_prompts.jsonl").write_text(
        "".join(json.dumps(p_, ensure_ascii=False) + "\n" for p_ in prompts), encoding="utf-8")

    left = sum(1 for it in items if re.search(CIT, it["reply"]))
    print(f"{len(items)} replies -> {len(batches)} batches of up to {a.batch_size}; "
          f"replies still holding an article citation: {left}; keymap: {keymap}")


if __name__ == "__main__":
    main()
