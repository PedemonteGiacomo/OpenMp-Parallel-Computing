# Monolithic version

This folder contains the single-process implementation of the grayscale filter
and related benchmarks.  Source files are under `src/` and headers in
`include/`.  Benchmark results are written to `results/`.

## Run without benchmark (compile with openMP flag activated)

To compile manually run:

```bash
make -C monolithic
```

For the version with Sobel edge detection:

```bash
make -f monolithic/Makefile_with_sobel -C monolithic
```

## Benchmark

Alternatively run the benchmarking script:

```bash
./monolithic/scripts/bench_and_plot_monolithic.sh monolithic/images/test.jpg "1 2 3 4 6" 1 1
```
Where each piece represent respectively:
- path of the script
- path of the image to apply the processing on
- list of number of threads to verify how performances changes
- number of runs for the thread which is running (to obtain an average result that will give a better perspective since each run is different)
- number of operations in the kernel: to obtain a more compute-bound algorithm set this parameter to an high value

The complete process to perform correctly the benchmark:

```bash
cd monolithic/
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt 
cd ..
./monolithic/scripts/bench_and_plot_monolithic.sh monolithic/images/test.jpg "1 2 3 4 6" 1 1
```