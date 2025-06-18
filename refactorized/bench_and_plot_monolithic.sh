#!/usr/bin/env bash
###############################################################################
# bench_and_plot_monolithic.sh
# Benchmark OpenMP (medie su più run) + grafici
###############################################################################
set -euo pipefail

IMG=${1:? "Specifica il file immagine, es: test.jpg"}
PHYS_CORE=$(lscpu | awk '/[Cc]ore/ && /socket/ {print $NF; exit}')
THREADS=${2:-"1 2 3 4 $PHYS_CORE"}
RUNS=${3:-10}               # ripetizioni per media
PASSES=${4:-1}              # ripetizioni del kernel dentro il programma

OUTDIR="results"
IMGDIR="$OUTDIR/images"
CSV="$OUTDIR/monolithic_bench.csv"
CFLAGS="-O3 -march=native -ffast-math -funroll-loops -fopenmp"
EXE=grayscale

mkdir -p "$OUTDIR" "$IMGDIR"

if ! command -v "$EXE" &>/dev/null && [ ! -x ./"$EXE" ]; then
  echo "Compilo $EXE..."
  gcc $CFLAGS main.c parallel_to_grayscale.c -lm -o "$EXE"
fi

echo "threads,avg_real_sec,std_real_sec,avg_cpu_pct,avg_mem_kb" > "$CSV"

for t in $THREADS; do
  echo ">> OMP_NUM_THREADS=$t  (×$RUNS run, kernel×$PASSES)"
  out_sub="$IMGDIR/$t"; mkdir -p "$out_sub"

  # accumulatori
  sum_r=0; sum_r2=0; sum_cpu=0; sum_mem=0

  for run in $(seq 1 "$RUNS"); do
    out_img="$out_sub/output_${run}.png"

    read real cpu mem < <(
      (OMP_NUM_THREADS=$t /usr/bin/time -f "%e %P %M" \
        ./"$EXE" "$IMG" "$out_img" "$PASSES") 2>&1 >/dev/null
    )
    cpu=${cpu%\%}

    # somma e somma dei quadrati per deviazione std
    sum_r=$(awk "BEGIN{print $sum_r+$real}")
    sum_r2=$(awk "BEGIN{print $sum_r2+($real*$real)}")
    sum_cpu=$(awk "BEGIN{print $sum_cpu+$cpu}")
    sum_mem=$(awk "BEGIN{print $sum_mem+$mem}")
  done

  avg_r=$(awk "BEGIN{print $sum_r/$RUNS}")
  std_r=$(awk "BEGIN{print sqrt($sum_r2/$RUNS - ($avg_r)^2)}")
  avg_cpu=$(awk "BEGIN{print $sum_cpu/$RUNS}")
  avg_mem=$(awk "BEGIN{print $sum_mem/$RUNS}")

  printf "%s,%.5f,%.5f,%.1f,%.0f\n" "$t" "$avg_r" "$std_r" "$avg_cpu" "$avg_mem" >> "$CSV"
done

echo -e "\n== Risultati (medie) ==" && column -s, -t "$CSV"

# -------- Grafici -----------------------------------------------------------
python3 - "$CSV" "$OUTDIR" << 'PY'
import sys, pandas as pd, matplotlib.pyplot as plt, os
csv, outdir = sys.argv[1], sys.argv[2]
df = pd.read_csv(csv).sort_values('threads')
df['speedup'] = df['avg_real_sec'].iloc[0] / df['avg_real_sec']

plt.figure(); plt.errorbar(df.threads, df.avg_real_sec, yerr=df.std_real_sec,
                           marker='o', capsize=3)
plt.xlabel('Thread OpenMP'); plt.ylabel('Tempo reale medio (s)')
plt.title('Tempo vs thread (media ± σ)'); plt.grid()
plt.savefig(os.path.join(outdir, 'tempo_vs_thread.png'), dpi=150)

plt.figure(); plt.plot(df.threads, df.speedup, marker='o')
plt.xlabel('Thread OpenMP'); plt.ylabel('Speed-up (×)')
plt.title('Speed-up'); plt.grid()
plt.savefig(os.path.join(outdir, 'speedup_vs_thread.png'), dpi=150)

print("\nGrafici in:", os.path.abspath(outdir))
PY

echo -e "\nFatto!  Risultati in  $(realpath "$OUTDIR")"
