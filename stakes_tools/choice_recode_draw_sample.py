"""Draw a fixed 10% random sample of part T and U replies for the reliability re-code.
Copies the chosen raw lines unchanged, in their original file order."""
import json, random
W = "C:/Users/15176/stakes_work/choice/"
lines = open(W + "choice_replies.jsonl", encoding="utf-8").read().splitlines()
pool = [i for i, l in enumerate(lines) if l.strip() and json.loads(l)["part"] in ("T", "U")]
k = round(len(pool) * 0.10)
chosen = sorted(random.Random(20261117).sample(pool, k))
with open(W + "recode/choice_recode_replies.jsonl", "w", encoding="utf-8", newline="\n") as f:
    f.write("".join(lines[i] + "\n" for i in chosen))
print(f"pool {len(pool)}, sampled {k}, seed 20261117")
