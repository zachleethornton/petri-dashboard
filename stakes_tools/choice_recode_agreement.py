"""Agreement between the original choice-v1 codes and the reliability re-code.
Joins both keymaps on (id, model, sample)."""
import json, collections
W = "C:/Users/15176/stakes_work/choice/"
def load(p): return [json.loads(l) for l in open(W + p, encoding="utf-8") if l.strip()]
t = lambda r: (r["id"], r["model"], r["sample"])
okm = {t(r): r for r in load("choice_keymap.jsonl")}
oc = {r["key"]: r for r in load("choice_codes.jsonl")}
rkm = load("recode/choice_recode_keymap.jsonl")
rc = {r["key"]: r for r in load("recode/choice_recode_codes.jsonl")}
pairs = []
for r in rkm:
    o = okm[t(r)]
    pairs.append((r, oc[o["key"]], rc[r["key"]]))
print("pairs", len(pairs))
def verdict(c): return c["choice"] if c["choice"] != "NA" else c["answer"]
def kappa(a, b):
    n = len(a); po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = collections.Counter(a), collections.Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / n / n
    return po, (po - pe) / (1 - pe) if pe < 1 else float("nan")
fields = [("verdict (answer or choice)", verdict)] + [(f, (lambda f: lambda c: c[f])(f)) for f in
          ["first_word_conflict", "misread", "reason", "discovery", "wishes"]]
groups = {"all": pairs,
          "T three-option": [p for p in pairs if p[0]["format"] == "THREE"],
          "U two-option": [p for p in pairs if p[0]["part"] == "U" and p[0]["format"] == "WORD"],
          "U yes/no": [p for p in pairs if p[0]["part"] == "U" and p[0]["format"] == "YN"]}
for g, ps in groups.items():
    print(f"\n{g} (n={len(ps)})")
    for name, fn in fields:
        po, k = kappa([fn(o) for _, o, _ in ps], [fn(n) for _, _, n in ps])
        print(f"  {name:28} agree {po*100:5.1f}%  kappa {k:5.2f}")
print("\nverdict disagreements (id | model | original -> recode):")
for r, o, n in pairs:
    if verdict(o) != verdict(n):
        print(f"  {r['id']:26} {r['model'].split('/')[2][:9]:9} s{r['sample']:<3} {verdict(o):12} -> {verdict(n)}")
print("\nverdict confusion (original, recode):", dict(collections.Counter((verdict(o), verdict(n)) for _, o, n in pairs if verdict(o) != verdict(n))))
