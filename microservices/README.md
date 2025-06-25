# Microservices Structure

This directory contains a microservice-based approach for the image processing algorithms.  Each service exposes its functionality over HTTP and can be deployed as a standalone container.

Currently only the **grayscale** service is implemented.  It reuses the OpenMP implementation from the monolithic version.

```
microservices/
  grayscale/
    app.py            # Flask application exposing /grayscale
    requirements.txt  # Python dependencies
    Dockerfile        # container image
    c/
      src/*.c         # OpenMP implementation
      include/*.h
      Makefile        # builds bin/grayscale
```

## Quick start

Run the service locally with Docker:

1. Build and start the container

   ```bash
   cd microservices/grayscale
   docker build -t grayscale-service .
   docker run --rm -p 5000:5000 grayscale-service
   ```

2. Send an image to the service

   ```bash
   python3 microservices/grayscale/test_client.py path/to/image.jpg output.png
   ```

   The service accepts a POST request to `/grayscale` with the file field `image`
   and returns the processed PNG.


### Benchmark script

To automate testing with multiple thread counts and runs, use `grayscale/scripts/bench_grayscale_service.sh`.
It performs repeated requests with the helper client and records average timings in CSV format.

Example:
```bash
./microservices/grayscale/scripts/bench_grayscale_service.sh path/to/image.jpg "1 2 4 6" 3 1000
```
This runs each thread configuration 3 times with 1000 kernel passes and prints a summary table.
The CSV is saved under `microservices/grayscale/results/service_bench.csv`.


The complete process (with all the dependencies to test the microservice with a test_client) is the following [no bench]:

```bash
cd microservices/grayscale
python3 -m venv .venv
source .venv/bin/activate
pip install -r client_requirements.txt
cd ../..
python3 microservices/grayscale/test_client.py images/more_than_one_mega_photo.jpg output.png
```

The client requires the `requests` library (`pip install requests`).

The script measures the request time and saves the processed image. Optional parameters
`--threads=N` and `--passes=N` allow tweaking the OpenMP runtime and the number of kernel
passes. These values are forwarded to the service which then invokes the underlying binary
accordingly.
