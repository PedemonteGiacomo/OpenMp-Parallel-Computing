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

## Running on Windows with WSL

The easiest way to run the project on Windows is through the
[Windows Subsystem for Linux](https://learn.microsoft.com/windows/wsl/).
The following steps assume an Ubuntu distribution but any recent Linux
will work.

1. **Install WSL**
   - Open PowerShell as administrator and run:

     ```powershell
     wsl --install -d Ubuntu
     ```

   - Restart the system if prompted and complete the Ubuntu setup.

2. **Install dependencies inside WSL**

   ```bash
   sudo apt update
   sudo apt install build-essential git python3 python3-pip time \
        python3-matplotlib python3-pandas
   ```

3. **Clone this repository (still inside WSL)**

   ```bash
   git clone <repo-url>
   cd OpenMp-Parallel-Computing
   ```

4. **Run the benchmark script**

   ```bash
   cd monolithic/scripts
   ./bench_and_plot_monolithic.sh ../images/test.jpg
   ```

Results and graphs will be available under `monolithic/results/`.
