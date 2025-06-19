#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT="$BASE_DIR/test_client.py"

IMG=${1:?"Provide image path"}
THREADS=${2:-"1"}
RUNS=${3:-5}
PASSES=${4:-1}
URL=${5:-http://localhost:5000}

OUTDIR="$BASE_DIR/results"
CSV="$OUTDIR/service_bench.csv"
mkdir -p "$OUTDIR"

# header
printf "threads,avg_request_sec,std_request_sec,avg_service_sec,std_service_sec\n" > "$CSV"

for t in $THREADS; do
  echo ">> threads=$t  (×$RUNS runs)"
  sum_r=0; sum_r2=0; sum_s=0; sum_s2=0
  for run in $(seq 1 "$RUNS"); do
    out=$(python3 "$CLIENT" "$IMG" /tmp/out.png --threads=$t --passes=$PASSES --url=$URL 2>/dev/null)
    req=$(echo "$out" | awk '/Request time/{print $3}' | tr -d 's')
    svc=$(echo "$out" | awk '/Service processing time/{print $4}' | tr -d 's')
    sum_r=$(awk "BEGIN{print $sum_r+$req}")
    sum_r2=$(awk "BEGIN{print $sum_r2+($req*$req)}")
    sum_s=$(awk "BEGIN{print $sum_s+$svc}")
    sum_s2=$(awk "BEGIN{print $sum_s2+($svc*$svc)}")
  done
  avg_r=$(awk "BEGIN{print $sum_r/$RUNS}")
  std_r=$(awk "BEGIN{print sqrt($sum_r2/$RUNS - ($avg_r)^2)}")
  avg_s=$(awk "BEGIN{print $sum_s/$RUNS}")
  std_s=$(awk "BEGIN{print sqrt($sum_s2/$RUNS - ($avg_s)^2)}")
  printf "%s,%.5f,%.5f,%.5f,%.5f\n" "$t" "$avg_r" "$std_r" "$avg_s" "$std_s" >> "$CSV"
done

echo -e "\n== Results ==" && column -s, -t "$CSV"
