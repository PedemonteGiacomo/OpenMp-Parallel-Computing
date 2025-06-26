#!/bin/bash
# safe_benchmark.sh - Run benchmarks with safer settings to prevent RabbitMQ overload

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_PATH="$SCRIPT_DIR/images/test.jpg"

echo "Running benchmark with safer settings to prevent RabbitMQ overload"
echo "Using image: $IMAGE_PATH"

# Usage info
if [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
  echo "Usage: $0 [passes] [threads]"
  echo "  passes: Number of kernel passes to perform (default: 1)"
  echo "  threads: Comma-separated list of thread counts (default: 1,2,4,6)"
  echo ""
  echo "Example: $0 3 \"1,4,8\""
  exit 0
fi

# Safer benchmark parameters:
# - Start with a small request count (1, 3, 5, 10)
# - Use longer delays between requests
# - Use more retries
# Get passed options or defaults
PASSES=${1:-1}
THREADS=${2:-"1,2,4,6"}

echo "Using kernel passes: $PASSES"
echo "Testing threads: $THREADS"

python3 "$SCRIPT_DIR/benchmark_plot.py" \
  "$IMAGE_PATH" \
  --counts "1,3,5,10" \
  --safer \
  --output "benchmark_safe.png" \
  --passes "$PASSES" \
  --threads "$THREADS"

echo "Benchmark complete. Results saved to benchmark_safe.png"
