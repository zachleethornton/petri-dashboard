"""Fixed-prompt stakes battery against the two hosted Petri targets.

Each prompt is sent as a single user message (no system turn, no prior turns) to the
same gateway endpoint Petri uses, with the exact request body Petri's auditor sends
(temperature 0.7, max_tokens 320, add_special_tokens false; everything else left to
the server, as in Petri). Work is done in (prompt, sample) pairs: both models are
called back to back, so a cut-off run has equal data for both. Results are appended
as they arrive; re-running resumes and skips (id, model, sample) already saved.

Usage: python run_stakes.py <bank.jsonl> <out.jsonl> [samples] [workers]
"""
import json, sys, time, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://api.swissai.svc.cscs.ch/v1"
MODELS = ["vvmoskvoretskii/pbmtsft/cite-epe-rmid-epe-3b", "vvmoskvoretskii/pbmtsft/util-t0mt-3b"]
KEY = (Path.home() / ".config/petri/swissai_api_key").read_text().strip()
FIELDS = ["id", "case", "rule", "variant", "rung", "order", "model", "sample", "reply", "finish_reason"]

bank_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
SAMPLES = int(sys.argv[3]) if len(sys.argv) > 3 else 10
WORKERS = int(sys.argv[4]) if len(sys.argv) > 4 else 8
err_path = out_path.with_name(out_path.stem + "_errors.jsonl")

bank = [json.loads(l) for l in bank_path.read_text(encoding="utf-8").splitlines() if l.strip()]
done = set()
if out_path.exists():
    for l in out_path.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l); done.add((r["id"], r["model"], r["sample"]))

lock = threading.Lock()
stop = threading.Event()
stop_reason = []


class ModelGone(Exception):
    pass


def call(model, prompt):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.7, "max_tokens": 320, "add_special_tokens": False}).encode()
    last = None
    for attempt in range(5):
        req = urllib.request.Request(f"{BASE}/chat/completions", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                d = json.loads(resp.read().decode("utf-8"))
            if "choices" not in d:
                raise RuntimeError(f"no choices: {str(d)[:300]}")
            c = d["choices"][0]
            return c["message"]["content"], c.get("finish_reason")
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:400]
            last = f"HTTP {e.code}: {msg}"
            if "No provider" in msg or e.code == 404:
                raise ModelGone(last)
            if e.code == 400:
                raise RuntimeError(last)  # not transient
        except Exception as e:  # network / timeout / bad JSON
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"gave up after retries: {last}")


def write(path, row):
    with lock, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def pair(item, sample):
    for model in MODELS:
        if stop.is_set():
            return
        if (item["id"], model, sample) in done:
            continue
        try:
            reply, fr = call(model, item["prompt"])
        except ModelGone as e:
            stop.set(); stop_reason.append(f"{model}: {e}")
            write(err_path, {"id": item["id"], "model": model, "sample": sample, "error": str(e)})
            return
        except Exception as e:
            write(err_path, {"id": item["id"], "model": model, "sample": sample, "error": str(e)})
            continue
        row = {k: item[k] for k in FIELDS[:6]}
        row.update(model=model, sample=sample, reply=reply, finish_reason=fr)
        write(out_path, row)


# sample-major order: every prompt gets sample 1 from both models before any gets sample 2
jobs = [(item, s) for s in range(1, SAMPLES + 1) for item in bank]
t0 = time.time()
with ThreadPoolExecutor(WORKERS) as ex:
    futs = [ex.submit(pair, it, s) for it, s in jobs]
    for i, f in enumerate(as_completed(futs), 1):
        f.result()
        if i % 72 == 0:
            print(f"{i}/{len(jobs)} pairs processed, {time.time() - t0:.0f}s", flush=True)

print("STOPPED: " + "; ".join(stop_reason) if stop.is_set() else "FINISHED", f"in {time.time() - t0:.0f}s")
