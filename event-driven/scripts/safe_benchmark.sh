#!/bin/bash
# safe_benchmark.sh - Run benchmarks with safer settings to prevent RabbitMQ overload

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_PATH="$SCRIPT_DIR/images/test.jpg"

echo "Running benchmark with safer settings to prevent RabbitMQ overload"
echo "Using image: $IMAGE_PATH"

# Safer benchmark parameters:
# - Start with a small request count (1, 3, 5, 10)
# - Use longer delays between requests
# - Use more retries
python3 "$SCRIPT_DIR/benchmark_plot.py" \
  "$IMAGE_PATH" \
  --counts "1,3,5,10" \
  --safer \
  --output "benchmark_safe.png"

echo "Benchmark complete. Results saved to benchmark_safe.png"
