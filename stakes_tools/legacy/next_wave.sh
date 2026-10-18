#!/bin/sh
# Validate coded batches, set aside invalid output (logged), print the next N batches to run.
cd ~/MR-Eval/stakes_v2_coding || exit 1
N=${1:-15}
out=$(python3 -I ../stakes_tools/check_codes.py .)
echo "$out" | grep '^batch' | while read -r _ b rest; do
  b=${b%:}; n=1; while [ -e "rejected/batch_$b.codes.try$n.jsonl" ]; do n=$((n+1)); done
  mv "batch_$b.codes.jsonl" "rejected/batch_$b.codes.try$n.jsonl"
  echo "$b try$n: ${rest#invalid: }" >> rejected/log.txt
  echo "set aside $b try$n: ${rest#invalid: }"
done
echo "$out" | tail -1 | sed 's/; to run:.*//'
echo "NEXT: $(echo "$out" | tail -1 | sed 's/.*to run: //' | tr ' ' '\n' | head -n "$N" | tr '\n' ' ')"
