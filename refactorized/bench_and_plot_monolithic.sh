#!/usr/bin/env bash
###############################################################################
# bench_and_plot.sh
# Benchmark monolitico OpenMP + grafici in un colpo solo
# Uso: ./bench_and_plot.sh <immagine_input> ["1 2 4 8"]
###############################################################################
set -euo pipefail

# -------- Parametri ----------------------------------------------------------
IMG=${1:? "Specifica il file immagine, es: test.jpg"}
# Rileva automaticamente i core fisici
PHYS_CORE=$(lscpu | awk '/[Cc]ore/ && /socket/ {print $NF; exit}')
THREADS=${2:-"1 2 3 4 $PHYS_CORE"}   # default: 1-4 + num core fisici
OUTDIR="results"                 # directory principale
IMGDIR="$OUTDIR/images"          # directory immagini per thread
CSV="$OUTDIR/monolithic_bench.csv"
EXE=grayscale

# -------- Crea cartelle ------------------------------------------------------
mkdir -p "$OUTDIR" "$IMGDIR"

# -------- Compilazione (se non esiste) ---------------------------------------
if ! command -v "$EXE" &>/dev/null && [ ! -x ./"$EXE" ]; then
  echo "Compilo $EXE..."
  gcc -O2 -fopenmp main.c parallel_to_grayscale.c -lm -o "$EXE"
fi

# -------- Benchmark ----------------------------------------------------------
echo "threads,real_sec,cpu_pct,mem_kb" > "$CSV"

for t in $THREADS; do
  echo ">> OMP_NUM_THREADS=$t"
  out_sub="$IMGDIR/$t"
  mkdir -p "$out_sub"
  out_img="$out_sub/output.png"

  # Esegui e cattura tempo, CPU, memoria
  read real cpu mem < <(
    (OMP_NUM_THREADS=$t /usr/bin/time -f "%e %P %M" \
      ./"$EXE" "$IMG" "$out_img") 2>&1 >/dev/null
  )
  cpu=${cpu%\%}   # togli il simbolo %
  echo "$t,$real,$cpu,$mem" >> "$CSV"
done

echo -e "\n== Risultati ==" && column -s, -t "$CSV"

# -------- Grafici via Python -------------------------------------------------
python3 - "$CSV" "$OUTDIR" << 'PY'
import sys, pandas as pd, matplotlib.pyplot as plt, os
csv, outdir = sys.argv[1], sys.argv[2]
df = pd.read_csv(csv); df['speedup'] = df['real_sec'].iloc[0]/df['real_sec']

plt.figure(); plt.plot(df.threads, df.real_sec, marker='o')
plt.xlabel('Thread OpenMP'); plt.ylabel('Tempo reale (s)')
plt.title('Tempo vs thread'); plt.grid(); \
plt.savefig(os.path.join(outdir,'tempo_vs_thread.png'), dpi=150)

plt.figure(); plt.plot(df.threads, df.speedup, marker='o')
plt.xlabel('Thread OpenMP'); plt.ylabel('Speed-up (×)')
plt.title('Speed-up'); plt.grid(); \
plt.savefig(os.path.join(outdir,'speedup_vs_thread.png'), dpi=150)

print("\nGrafici in:", os.path.abspath(outdir))
PY

echo -e "\nFatto!  Risultati in  $(realpath "$OUTDIR")"
