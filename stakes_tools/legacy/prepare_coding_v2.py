"""Step 2 prep for the stakes v2 battery: blind keys, citation stripping, shuffled batches.

Reads the replies file and the rubric, then writes:
  <keymap>                       key -> (id, model, sample)   (never shown to coders)
  <batch_dir>/batch_NNN.md       rubric + 25 items (KEY, QUESTION, cleaned REPLY), nothing else
  <batch_dir>/batches.json       batch number -> list of keys (for validation)

Usage: python prepare_coding.py <replies.jsonl> <rubric.md> <keymap.jsonl> <batch_dir> [batch_size]
"""
import json, re, secrets, random, sys
from pathlib import Path

replies_path, rubric_path, keymap_path, batch_dir = map(Path, sys.argv[1:5])
SIZE = int(sys.argv[5]) if len(sys.argv) > 5 else 25

# One citation: [3.3], [8.5], [1.2,1.4], [1.2, 1.4], [8.2-8.6]. A run of them, possibly joined by
# dashes ("[8.2]-[8.6]") or adjacent ("[2.1][5.2]"), is removed as a unit.
CIT = r"\[\s*\d+(?:\.\d+)*(?:\s*[,;–—-]\s*\d+(?:\.\d+)*)*\s*\]"
RUN = re.compile(rf"[ \t]*{CIT}(?:\s*[–—-]?\s*{CIT})*")


def clean(text):
    out = RUN.sub("", text)
    out = re.sub(r"[ \t]+([.,;:!?)])(?!\d)", r"\1", out)   # no space left before punctuation (not ".8")
    out = re.sub(r"\(\s*\)", "", out)                 # "( )" left by "([3.3])"
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


rows = [json.loads(l) for l in replies_path.read_text(encoding="utf-8").splitlines() if l.strip()]
rubric = rubric_path.read_text(encoding="utf-8").strip()

keys = set()
items = []
for r in rows:
    k = "k" + secrets.token_hex(5)
    while k in keys:
        k = "k" + secrets.token_hex(5)
    keys.add(k)
    items.append({"key": k, "id": r["id"], "model": r["model"], "sample": r["sample"],
                  "question": r["question"], "reply": clean(r["reply"])})

random.SystemRandom().shuffle(items)

keymap_path.write_text("".join(json.dumps({"key": it["key"], "id": it["id"], "model": it["model"],
                                           "sample": it["sample"]}) + "\n" for it in items), encoding="utf-8")

batch_dir.mkdir(parents=True, exist_ok=True)
batches = {}
for b, start in enumerate(range(0, len(items), SIZE), 1):
    chunk = items[start:start + SIZE]
    batches[f"{b:03d}"] = [it["key"] for it in chunk]
    parts = [rubric, "", "## Items", ""]
    for it in chunk:
        parts += [f"### KEY: {it['key']}", "", f"QUESTION: {it['question']}", "", "REPLY:", "",
                  it["reply"], "", "---", ""]
    (batch_dir / f"batch_{b:03d}.md").write_text("\n".join(parts), encoding="utf-8")
(batch_dir / "batches.json").write_text(json.dumps(batches), encoding="utf-8")

left = [it["key"] for it in items if re.search(CIT, it["reply"])]
print(f"{len(items)} items, {len(batches)} batches of up to {SIZE}; "
      f"replies still containing an article citation after cleaning: {len(left)}")
