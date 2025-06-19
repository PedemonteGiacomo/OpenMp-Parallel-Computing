# Monolithic version

This folder contains the single-process implementation of the grayscale filter
and related benchmarks.  Source files are under `src/` and headers in
`include/`.  Benchmark results are written to `results/`.

To compile manually run:

```bash
make -C monolithic
```

For the version with Sobel edge detection:

```bash
make -f monolithic/Makefile_with_sobel -C monolithic
```

Alternatively run the benchmarking script:

```bash
./scripts/bench_and_plot_monolithic.sh images/test.jpg
```

