# Monolithic version

This folder contains the single-process implementation of the grayscale filter
and related benchmarks.  Source files are under `src/` and headers in
`include/`.  Benchmark results are written to `results/`.

## Prerequisites

You need a C compiler with OpenMP support and Python with a few
packages.  On Debian/Ubuntu (or WSL with Ubuntu) run:

```bash
sudo apt update
sudo apt install build-essential time python3 python3-pip \
     python3-matplotlib python3-pandas
```

These packages provide `gcc`, `make`, `/usr/bin/time` and the Python
libraries used by the benchmarking script.

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

Running the script creates `monolithic/bin/grayscale` if it does not
exist and writes CSV data and plots under `monolithic/results/`.
