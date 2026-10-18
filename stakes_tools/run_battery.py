#!/usr/bin/env python3
"""Run a fixed-prompt stakes battery against served models (no Petri, no judging).

Each bank prompt is sent as the ONLY user turn of a fresh conversation (no system turn,
no prior turns) to an OpenAI-compatible /chat/completions endpoint. Work is done in
(prompt, sample) pairs: every model is called for the same (prompt, sample) back to back,
so a run cut short still has equal data per model. Replies are appended as they arrive.

Resumable: (id, model, sample) triples already in <prefix>_replies.jsonl are skipped, so
re-running the same command continues where it stopped. Error rows are NOT treated as
done; a re-run retries them.

Outputs
  <prefix>_replies.jsonl  one line per reply: every bank field except `prompt`, in bank
                          order (extra/factor columns carried through unchanged), then
                          model, sample, reply, finish_reason
  <prefix>_errors.jsonl   one line per failed call: id, model, sample, status, error

Environment (never hard-code values)
  SWISSAI_API_KEY       bearer token; if unset, read from $PETRI_KEY_FILE
  PETRI_KEY_FILE        default ~/.config/petri/swissai_api_key (Viktor's onboarding)
  PETRI_GATEWAY_URL     default https://api.swissai.svc.cscs.ch/v1

Example (the v2 battery):
  python3 -I run_battery.py --bank banks/stakes_bank_v2.jsonl --samples 30 \
      --out-prefix out/stakes_v2
"""
import argparse, json, os, random, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REQUIRED = ["id", "case", "rule", "variant", "rung", "direction", "yes_means", "question", "prompt"]
DEFAULT_MODELS = "vvmoskvoretskii/pbmtsft/cite-epe-rmid-epe-3b,vvmoskvoretskii/pbmtsft/util-t0mt-3b"
DEFAULT_URL = "https://api.swissai.svc.cscs.ch/v1"


def api_key():
    k = os.environ.get("SWISSAI_API_KEY", "").strip()
    if k:
        return k
    f = Path(os.environ.get("PETRI_KEY_FILE", Path.home() / ".config/petri/swissai_api_key")).expanduser()
    if not f.is_file():
        sys.exit("no API key: set SWISSAI_API_KEY or PETRI_KEY_FILE (see HANDOFF.md)")
    return f.read_text().strip()


def load_bank(path):
    rows, seen = [], set()
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        missing = [k for k in REQUIRED if k not in r]
        if missing:
            sys.exit(f"bank line {n} (id={r.get('id')!r}) is missing fields: {missing}")
        if r["id"] in seen:
            sys.exit(f"bank line {n}: duplicate id {r['id']!r}")
        seen.add(r["id"])
        rows.append(r)
    if not rows:
        sys.exit("bank is empty")
    return rows


class ModelGone(Exception):
    pass


class Runner:
    def __init__(self, a, key):
        self.a, self.key = a, key
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.stop_reason = []
        self.retries = 0
        self.errors = 0
        self.written = {}

    def body(self, model, prompt):
        b = {"model": model, "messages": [{"role": "user", "content": prompt}],
             "temperature": self.a.temperature, "max_tokens": self.a.max_tokens,
             "add_special_tokens": False}
        if not self.a.omit_top_p:
            b["top_p"] = self.a.top_p
        return json.dumps(b).encode()

    def call(self, model, prompt):
        """Return (reply, finish_reason). Raises ModelGone, or RuntimeError(status, msg)."""
        data, last = self.body(model, prompt), None
        for attempt in range(self.a.max_retries + 1):
            req = urllib.request.Request(f"{self.a.base_url}/chat/completions", data=data, method="POST",
                                         headers={"Authorization": f"Bearer {self.key}",
                                                  "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.a.timeout) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                c = d["choices"][0]
                return c["message"]["content"], c.get("finish_reason")
            except urllib.error.HTTPError as e:
                msg = e.read().decode("utf-8", "replace")[:500]
                if "No provider" in msg or e.code == 404:
                    raise ModelGone(f"HTTP {e.code}: {msg}")
                if e.code == 429 or e.code >= 500:
                    last = (e.code, msg)
                else:  # 400 = context overflow / bad request: not transient, log and move on
                    raise RuntimeError(e.code, msg)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                last = ("network", f"{type(e).__name__}: {e}")
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                last = ("bad_response", f"{type(e).__name__}: {e}")
            if attempt < self.a.max_retries:
                with self.lock:
                    self.retries += 1
                time.sleep(min(60, 2 ** attempt) + random.random())
        raise RuntimeError(last[0], f"gave up after {self.a.max_retries} retries: {last[1]}")

    def write(self, path, row):
        with self.lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def pair(self, item, sample, done):
        for model in self.a.models:
            if self.stop.is_set():
                return
            if (item["id"], model, sample) in done:
                continue
            try:
                reply, fr = self.call(model, item["prompt"])
            except ModelGone as e:
                self.stop.set()
                self.stop_reason.append(f"{model}: {e}")
                self.write(self.err_path, {"id": item["id"], "model": model, "sample": sample,
                                           "status": "model_gone", "error": str(e)})
                with self.lock:
                    self.errors += 1
                return
            except RuntimeError as e:
                status, msg = e.args if len(e.args) == 2 else ("error", str(e))
                self.write(self.err_path, {"id": item["id"], "model": model, "sample": sample,
                                           "status": status, "error": msg})
                with self.lock:
                    self.errors += 1
                continue
            row = {k: v for k, v in item.items() if k != "prompt"}
            row.update(model=model, sample=sample, reply=reply, finish_reason=fr)
            self.write(self.out_path, row)
            with self.lock:
                self.written[model] = self.written.get(model, 0) + 1

    def run(self, bank):
        a = self.a
        self.out_path = Path(f"{a.out_prefix}_replies.jsonl")
        self.err_path = Path(f"{a.out_prefix}_errors.jsonl")
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        done = set()
        if self.out_path.exists():
            for l in self.out_path.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    r = json.loads(l)
                    done.add((r["id"], r["model"], r["sample"]))
        jobs = [(it, s) for s in range(1, a.samples + 1) for it in bank]  # sample-major
        todo = sum(1 for it, s in jobs for m in a.models if (it["id"], m, s) not in done)
        print(f"bank {len(bank)} prompts x {len(a.models)} models x {a.samples} samples; "
              f"{len(done)} already done, {todo} to call", flush=True)
        t0 = time.time()
        with ThreadPoolExecutor(a.workers) as ex:
            futs = [ex.submit(self.pair, it, s, done) for it, s in jobs]
            step = max(1, len(futs) // 10)
            for i, f in enumerate(as_completed(futs), 1):
                f.result()
                if i % step == 0:
                    print(f"  {i}/{len(futs)} pairs, {time.time() - t0:.0f}s", flush=True)
        # final count line, from the files on disk (includes earlier resumed runs)
        per, trunc = {m: 0 for m in a.models}, 0
        for l in self.out_path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                per[r["model"]] = per.get(r["model"], 0) + 1
                trunc += r.get("finish_reason") == "length"
        ok = {(r["id"], r["model"], r["sample"]) for r in map(json.loads, filter(
            str.strip, self.out_path.read_text(encoding="utf-8").splitlines()))}
        unresolved = set()
        if self.err_path.exists():
            for l in self.err_path.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    e = json.loads(l)
                    if (e["id"], e["model"], e["sample"]) not in ok:
                        unresolved.add((e["id"], e["model"], e["sample"]))
        status = "STOPPED (" + "; ".join(self.stop_reason) + ")" if self.stop.is_set() else "FINISHED"
        print(f"{status} in {time.time() - t0:.0f}s")
        print("COUNT " + ", ".join(f"{m.split('/')[-1]}={n}" for m, n in per.items())
              + f" | expected per model={len(bank) * a.samples} | truncated={trunc}"
              + f" | unresolved errors={len(unresolved)} | errors this run={self.errors}"
              + f" | retries this run={self.retries}")
        return 1 if self.stop.is_set() else 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bank", required=True, help="bank .jsonl (fields: " + ", ".join(REQUIRED) + ", plus any extras)")
    p.add_argument("--models", default=DEFAULT_MODELS, help="comma-separated gateway model ids")
    p.add_argument("--samples", type=int, default=30)
    p.add_argument("--out-prefix", required=True, help="writes <prefix>_replies.jsonl and <prefix>_errors.jsonl")
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--max-tokens", type=int, default=320)
    p.add_argument("--top-p", type=float, default=0.9)
    p.add_argument("--omit-top-p", action="store_true",
                   help="do not send top_p (exactly the v1/v2 request body; the server then applies "
                        "the model's generation_config top_p, which is 0.9 for both hosted models)")
    p.add_argument("--first", type=int, default=0, help="use only the first N bank rows (dry runs)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-retries", type=int, default=6)
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument("--base-url", default=os.environ.get("PETRI_GATEWAY_URL", DEFAULT_URL))
    a = p.parse_args()
    a.models = [m.strip() for m in a.models.split(",") if m.strip()]
    bank = load_bank(a.bank)
    if a.first:
        bank = bank[:a.first]
    sys.exit(Runner(a, api_key()).run(bank))


if __name__ == "__main__":
    main()
