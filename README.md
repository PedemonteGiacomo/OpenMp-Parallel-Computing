# OpenMP Image Processing

This repository contains experiments with OpenMP for image processing.  The
original examples from the upstream repository are kept in `old/` while the
`monolithic/` directory holds a refactored version that performs the grayscale
conversion in place.

```
monolithic/
  src/       # C sources
  include/   # headers
  images/    # sample images
  bin/       # compiled binaries (ignored by git)
  results/   # benchmark outputs
  scripts/   # helper scripts
```

Use the helper script to compile and benchmark the monolithic program:

```bash
cd monolithic/scripts
./bench_and_plot_monolithic.sh ../images/test.jpg
```

The script builds the program if needed and saves results inside
`monolithic/results`.

## Microservices

A new directory `microservices/` shows how the processing algorithms can be exposed as standalone services. The first available service is `grayscale`, which wraps the OpenMP grayscale conversion inside a small Flask application and Docker container. See `microservices/README.md` for details on building and running the container.
