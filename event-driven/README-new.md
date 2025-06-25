# Event-Driven Architecture with OpenMP Performance Testing

This system demonstrates a microservices-based event-driven architecture using RabbitMQ and MinIO for image processing with OpenMP. The system includes tools for load testing, benchmarking, and visualizing OpenMP parallel performance.

## Table of Contents
1. [Components](#components)
2. [Setting Up](#setting-up)
3. [Running Tests](#running-tests)
   - [Basic Testing](#basic-testing)
   - [Load Testing](#load-testing) 
   - [Benchmark Testing](#benchmark-testing)
   - [Safe Benchmark Mode](#safe-benchmark-mode)
4. [Monitoring and Managing](#monitoring-and-managing)
   - [RabbitMQ Monitoring](#rabbitmq-monitoring)
   - [Service Recovery](#service-recovery)
5. [Understanding Results](#understanding-results)
   - [OpenMP Performance Metrics](#openmp-performance-metrics)
   - [Visualizing Results](#visualizing-results)
   - [Prometheus Metrics](#prometheus-metrics)
6. [Advanced Usage](#advanced-usage)
   - [Tuning for Scale](#tuning-for-scale)
   - [Adding Custom Tests](#adding-custom-tests)
7. [Troubleshooting](#troubleshooting)
8. [Adding New Processing Services](#adding-new-processing-services)

## Components

- **MinIO** – Local object storage for uploaded and processed images
- **RabbitMQ** – Message queue for decoupling services
- **grayscale_service** – Worker that performs the grayscale conversion using OpenMP
- **frontend** – Flask application for submitting images and viewing results
- **Testing Tools** – Scripts for load testing, benchmarking, and monitoring

## Setting Up

1. **Build and start the stack**

   ```bash
   cd event-driven
   docker compose up --build
   ```

2. **Create a Python virtual environment** (recommended)

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r scripts/requirements.txt
   ```

3. **Verify services are running**

   Check that all services are healthy:
   ```bash
   docker compose ps
   ```

   Test with a single image:
   ```bash
   python3 scripts/load_test.py images/test.jpg
   ```

## Running Tests

### Basic Testing

The simplest way to test the system is through the web UI:

1. Open `http://localhost:8080` in your browser
2. Upload an image
3. Select thread counts (1, 2, 4, 6) and number of runs
4. Submit and observe the processing time charts

### Load Testing

The `load_test.py` script allows you to submit multiple requests with configurable concurrency:

```bash
python3 scripts/load_test.py images/test.jpg --count 10 --concurrency 4 --delay 1.0
```

Parameters:
- `--count`: Number of image processing requests to send
- `--concurrency`: Number of concurrent workers
- `--delay`: Delay between requests in seconds (prevents overloading)
- `--timeout`: Maximum time to wait for processing (default: 60s)
- `--retries`: Number of retry attempts if a request fails (default: 3)
- `--debug`: Print detailed debug information

Example for testing different image sizes:
```bash
# Test with a small image
python3 scripts/load_test.py images/test.jpg --count 5 --concurrency 2

# Test with a larger image
python3 scripts/load_test.py images/more_than_one_mega_photo.jpg --count 5 --concurrency 2
```

### Benchmark Testing

For comprehensive performance testing across different request volumes:

```bash
python3 scripts/benchmark_plot.py images/test.jpg --counts "1,5,10,20" --concurrency 4
```

Parameters:
- `--counts`: Comma-separated list of request counts to test
- `--concurrency`: Maximum number of concurrent requests
- `--output`: Filename for the output graph (default: benchmark.png)
- `--safer`: Use more conservative settings to prevent overloading

Example for focused OpenMP thread scaling test:
```bash
# Test with small batches but multiple thread combinations
python3 scripts/benchmark_plot.py images/test.jpg --counts "1,3,5" --safer
```

### Safe Benchmark Mode

To avoid overwhelming RabbitMQ during benchmarking, use the safe benchmark script:

```bash
./scripts/safe_benchmark.sh
```

This script runs benchmarks with conservative parameters that prevent RabbitMQ from being overloaded.

## Monitoring and Managing

### RabbitMQ Monitoring

Monitor RabbitMQ queue status during testing:

```bash
# Check queue status
python3 scripts/manage_rabbitmq.py status

# Monitor queues continuously
python3 scripts/manage_rabbitmq.py monitor

# Purge queues when they get overloaded
python3 scripts/manage_rabbitmq.py purge
```

### Service Recovery

If services crash or RabbitMQ becomes overloaded, use the recovery script:

```bash
./scripts/reset_services.sh
```

This interactive script provides options to:
- Check service status
- Purge RabbitMQ queues
- Restart individual services
- Perform an ordered restart of the entire system
- Monitor RabbitMQ queues

## Understanding Results

### OpenMP Performance Metrics

The system provides several ways to measure OpenMP performance:

1. **Frontend Charts**: The web UI displays two charts:
   - Execution time for each thread count
   - Speed-up factor relative to single-thread performance

2. **Process Time Metrics**: The grayscale service records processing time in Prometheus:
   - `grayscale_process_seconds`: Time spent executing the OpenMP algorithm
   - Accessible at `http://localhost:8001/`

3. **Benchmark Reports**: The benchmark script generates plots showing:
   - Average latency by request count
   - 95th percentile latency
   - Throughput (requests/second)
   - Success rate

Example of extracting raw OpenMP timing data:
```bash
# Run a single request and extract timing data
curl -s http://localhost:8001/ | grep "grayscale_process_seconds"
```

### Visualizing Results

Benchmark plots (generated at `benchmark.png` or `benchmark_safe.png`) contain four panels:

1. **Average Latency**: Total request processing time as request count increases
2. **95th Percentile Latency**: Worst-case performance indicator
3. **Throughput**: Requests per second the system can handle
4. **Prometheus Averages**: Breakdown of time spent in queue, processing, and total

These visualizations help identify:
- OpenMP scaling efficiency across thread counts
- System bottlenecks as load increases
- Queue saturation points

### Prometheus Metrics

Available metrics endpoints:

- **Frontend**: `http://localhost:8000/metrics`
  - `frontend_request_seconds`: Time from upload to completed processing
  - `frontend_publish_total`: Total messages published to the queue
  - `frontend_processed_total`: Total processed notifications received

- **Worker**: `http://localhost:8001/`
  - `grayscale_queue_wait_seconds`: Time messages spend waiting in the queue
  - `grayscale_process_seconds`: Time spent executing the OpenMP algorithm
  - `grayscale_startup_seconds`: Time from container start to first processed message
  - `grayscale_failures_total`: Number of processing failures
  - `grayscale_reconnect_attempts`: Connection retry attempts to RabbitMQ

## Advanced Usage

### Tuning for Scale

Adjust these parameters for handling larger workloads:

1. **RabbitMQ Prefetch Count**: Controls how many messages the worker processes simultaneously
   ```bash
   # Start container with custom prefetch count
   PREFETCH_COUNT=2 docker compose up grayscale_service
   ```

2. **Thread Allocation**: Balance between parallelism and resource contention
   ```bash
   # Test different thread combinations
   python3 scripts/load_test.py images/test.jpg --count 5 --concurrency 2
   ```

3. **Batch Size**: Adjust request counts based on image size
   ```bash
   # For larger images, use smaller batches
   python3 scripts/benchmark_plot.py images/more_than_one_mega_photo.jpg --counts "1,3,5"
   ```

### Adding Custom Tests

Create custom test scenarios by combining available tools:

```bash
# Example: Test recovery from queue saturation
./scripts/reset_services.sh  # Start with clean services
python3 scripts/benchmark_plot.py images/test.jpg --counts "1,20,50" # Run intensive benchmark
./scripts/reset_services.sh  # Recover system
python3 scripts/manage_rabbitmq.py monitor # Check queue health
```

## Troubleshooting

Common issues and solutions:

1. **RabbitMQ Overload**
   - Symptoms: 500 errors, connection refusals, workers crashing
   - Solution: Run `./scripts/reset_services.sh` and select "Purge RabbitMQ queues"

2. **Service Crashes**
   - Symptoms: Services become unresponsive
   - Solution: Use ordered restart option in `reset_services.sh`

3. **Benchmark Failures**
   - Symptoms: Incomplete plots, missing data points
   - Solution: Use `--safer` flag or reduce concurrency and counts

4. **Slow Processing**
   - Symptoms: Very long processing times
   - Solution: Check if larger images are being used; ensure no other intensive processes are running

## Adding New Processing Services

To add a new OpenMP-based processing service:

1. **Create a new folder** under `event-driven/` (for example `blur_service`)
2. **Define queues** for the service in its app.py
3. **Update docker-compose.yml** to include the new service
4. **Extend the frontend** to offer the new processing option

For detailed instructions, see the "Adding a new processing service" section in the original documentation.

### Example Test Scenarios

1. **OpenMP Thread Scaling Test**
   ```bash
   # Access the web UI and test all thread counts with the same image
   # Compare the speedup chart to evaluate OpenMP scaling efficiency
   ```

2. **System Throughput Test**
   ```bash
   # Test how many images the system can process per second
   python3 scripts/benchmark_plot.py images/test.jpg --counts "1,10,20,30" --concurrency 5
   # Examine the throughput graph to find the saturation point
   ```

3. **Large Image Test**
   ```bash
   # Test with a high-resolution image to evaluate memory handling
   python3 scripts/load_test.py images/more_than_one_mega_photo.jpg --count 3 --concurrency 1
   ```

4. **Recovery Test**
   ```bash
   # Deliberately overload the system then test recovery
   python3 scripts/benchmark_plot.py images/test.jpg --counts "50" --concurrency 10
   # Then run the recovery script
   ./scripts/reset_services.sh
   ```
