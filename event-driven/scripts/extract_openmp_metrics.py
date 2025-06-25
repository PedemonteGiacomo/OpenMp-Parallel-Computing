#!/usr/bin/env python3
"""
OpenMP Performance Metrics Extractor for Event-Driven System

This script extracts and analyzes OpenMP performance metrics from the grayscale service,
focusing on processing times across different thread counts. It can either:
1. Extract metrics from Prometheus endpoints
2. Run a controlled test with different thread configurations
3. Generate detailed performance report

Usage:
  python3 extract_openmp_metrics.py --mode prometheus
  python3 extract_openmp_metrics.py --mode test --image images/test.jpg --threads 1,2,4,6
  python3 extract_openmp_metrics.py --mode report --output openmp_report.csv
"""
import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import defaultdict

import matplotlib.pyplot as plt
import requests

# Default settings
FRONTEND_URL = "http://localhost:8080/"
METRICS_URL = "http://localhost:8001/"


def extract_prometheus_metrics():
    """Extract OpenMP processing time metrics from Prometheus endpoint"""
    try:
        print("Fetching OpenMP processing metrics from Prometheus...")
        response = requests.get(METRICS_URL, timeout=5)
        
        if response.status_code != 200:
            print(f"Error: Failed to retrieve metrics (HTTP {response.status_code})")
            return None
            
        metrics = response.text
        
        # Extract processing time metrics
        process_time_data = {}
        
        # Extract histogram buckets
        process_buckets = {}
        bucket_pattern = r'grayscale_process_seconds_bucket\{le="([^"]+)"\}\s+([\d\.]+)'
        for match in re.finditer(bucket_pattern, metrics):
            bucket = float(match.group(1))
            count = float(match.group(2))
            process_buckets[bucket] = count
            
        # Extract sum and count
        sum_match = re.search(r'grayscale_process_seconds_sum\s+([\d\.]+)', metrics)
        count_match = re.search(r'grayscale_process_seconds_count\s+([\d\.]+)', metrics)
        
        if sum_match and count_match:
            total_sum = float(sum_match.group(1))
            total_count = int(float(count_match.group(1)))
            avg_time = total_sum / total_count if total_count > 0 else 0
            
            process_time_data = {
                "total_sum": total_sum,
                "total_count": total_count,
                "average_time": avg_time,
                "buckets": process_buckets
            }
            
            # Calculate approximate percentiles from buckets
            if process_buckets:
                sorted_buckets = sorted(process_buckets.items())
                if len(sorted_buckets) > 1:
                    p50_idx = int(total_count * 0.5)
                    p95_idx = int(total_count * 0.95)
                    p99_idx = int(total_count * 0.99)
                    
                    # Find bucket that contains the percentile
                    current_count = 0
                    for bucket, count in sorted_buckets:
                        if current_count < p50_idx <= count:
                            process_time_data["p50"] = bucket
                        if current_count < p95_idx <= count:
                            process_time_data["p95"] = bucket
                        if current_count < p99_idx <= count:
                            process_time_data["p99"] = bucket
                        current_count = count
        
        # Get failure metrics
        failure_match = re.search(r'grayscale_failures_total\s+([\d\.]+)', metrics)
        if failure_match:
            process_time_data["failures"] = int(float(failure_match.group(1)))
            
        return process_time_data
    
    except Exception as e:
        print(f"Error extracting metrics: {e}")
        return None


def run_controlled_test(image_path, threads, repeats=3):
    """
    Run a controlled test with specific thread counts and measure OpenMP performance
    
    Args:
        image_path: Path to test image
        threads: List of thread counts to test
        repeats: Number of times to repeat each test for statistical significance
    """
    thread_results = {}
    
    print(f"Running controlled test with thread counts {threads}, {repeats} repeats each")
    
    for thread_count in threads:
        thread_times = []
        
        print(f"\nTesting with {thread_count} threads:")
        for i in range(repeats):
            print(f"  Repeat {i+1}/{repeats}...", end="", flush=True)
            
            try:
                # Submit with specified thread count
                with open(image_path, 'rb') as f:
                    files = {'image': f}
                    data = {'threads': [thread_count], 'repeat': 1}  # Just one repeat per submission
                    
                    # Submit request
                    start_time = time.time()
                    resp = requests.post(FRONTEND_URL, files=files, data=data)
                    
                    if resp.status_code != 200:
                        print(f" Failed (HTTP {resp.status_code})")
                        continue
                        
                    # Extract key to poll for results
                    m = re.search(r'/status\?key=([^"\']+)', resp.text)
                    if not m:
                        print(" Failed (Key not found)")
                        continue
                        
                    key = m.group(1)
                    
                    # Poll for completion
                    while True:
                        time.sleep(0.5)
                        st = requests.get(f"{FRONTEND_URL}status", params={'key': key})
                        if st.status_code != 200:
                            print(" Failed (Status error)")
                            break
                            
                        data = st.json()
                        if data.get('processed'):
                            # Extract the processing time for this thread count
                            elapsed = time.time() - start_time
                            thread_time = data.get('times', {}).get(str(thread_count))
                            
                            if thread_time is not None:
                                thread_times.append(thread_time)
                                print(f" Done ({thread_time:.3f}s)")
                            else:
                                print(" Done (No timing data)")
                            break
            
            except Exception as e:
                print(f" Error: {e}")
        
        # Calculate statistics if we have results
        if thread_times:
            thread_results[thread_count] = {
                "times": thread_times,
                "mean": statistics.mean(thread_times),
                "min": min(thread_times),
                "max": max(thread_times),
                "stddev": statistics.stdev(thread_times) if len(thread_times) > 1 else 0
            }
    
    # Calculate speedup relative to thread_count=1
    if 1 in thread_results and thread_results[1]["mean"] > 0:
        base_time = thread_results[1]["mean"]
        for tc in thread_results:
            thread_results[tc]["speedup"] = base_time / thread_results[tc]["mean"]
    
    return thread_results


def generate_report(output_file=None):
    """
    Generate a comprehensive report of OpenMP performance by collecting
    and analyzing metrics from recent tests.
    """
    # First get current metrics
    metrics = extract_prometheus_metrics()
    
    if not metrics:
        print("Error: Unable to retrieve metrics for report")
        return False
    
    # Try to get processed job information from frontend
    processed_jobs = defaultdict(list)
    try:
        # Fetch the most recent jobs (just informational, might not be available)
        r = requests.get(FRONTEND_URL + "metrics")
        if r.status_code == 200:
            # Count processed jobs
            count_match = re.search(r'frontend_processed_total\s+([\d\.]+)', r.text)
            if count_match:
                processed_count = int(float(count_match.group(1)))
                print(f"Total processed jobs: {processed_count}")
    except:
        pass  # Ignore frontend metrics errors
    
    # Prepare report data
    report_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": metrics,
        "processed_jobs": dict(processed_jobs),
    }
    
    # Print summary
    print("\nOpenMP Performance Summary:")
    print(f"Total executions: {metrics['total_count']}")
    print(f"Average execution time: {metrics['average_time']:.3f} seconds")
    if "p50" in metrics:
        print(f"Median execution time: <= {metrics['p50']:.3f} seconds")
    if "p95" in metrics:
        print(f"95th percentile execution time: <= {metrics['p95']:.3f} seconds")
    if "failures" in metrics:
        print(f"Failed executions: {metrics['failures']}")
    
    # Save to file if requested
    if output_file:
        if output_file.endswith('.json'):
            with open(output_file, 'w') as f:
                json.dump(report_data, f, indent=2)
        elif output_file.endswith('.csv'):
            # Write a simplified CSV with bucket information
            with open(output_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Metric', 'Value'])
                writer.writerow(['Timestamp', report_data['timestamp']])
                writer.writerow(['Total Count', metrics['total_count']])
                writer.writerow(['Average Time', metrics['average_time']])
                if "p50" in metrics:
                    writer.writerow(['P50', metrics['p50']])
                if "p95" in metrics:
                    writer.writerow(['P95', metrics['p95']])
                if "p99" in metrics:
                    writer.writerow(['P99', metrics['p99']])
                if "failures" in metrics:
                    writer.writerow(['Failures', metrics['failures']])
                
                writer.writerow([])
                writer.writerow(['Bucket', 'Count'])
                for bucket, count in sorted(metrics['buckets'].items()):
                    writer.writerow([bucket, count])
        else:
            # Default to text format
            with open(output_file, 'w') as f:
                f.write("OpenMP Performance Report\n")
                f.write(f"Generated: {report_data['timestamp']}\n\n")
                f.write(f"Total executions: {metrics['total_count']}\n")
                f.write(f"Average execution time: {metrics['average_time']:.3f} seconds\n")
                if "p50" in metrics:
                    f.write(f"Median execution time: <= {metrics['p50']:.3f} seconds\n")
                if "p95" in metrics:
                    f.write(f"95th percentile execution time: <= {metrics['p95']:.3f} seconds\n")
                if "failures" in metrics:
                    f.write(f"Failed executions: {metrics['failures']}\n")
                
                f.write("\nHistogram Buckets:\n")
                for bucket, count in sorted(metrics['buckets'].items()):
                    f.write(f"  <= {bucket:.3f}s: {count}\n")
        
        print(f"\nReport saved to {output_file}")
    
    return True


def plot_thread_scaling(results, output_file="openmp_scaling.png"):
    """Plot thread scaling results"""
    if not results:
        print("No results to plot")
        return
        
    thread_counts = sorted(results.keys())
    execution_times = [results[tc]["mean"] for tc in thread_counts]
    speedups = [results[tc].get("speedup", 1.0) for tc in thread_counts]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    
    # Plot execution time
    ax1.plot(thread_counts, execution_times, 'o-', color='blue')
    ax1.set_title('OpenMP Execution Time by Thread Count')
    ax1.set_xlabel('Thread Count')
    ax1.set_ylabel('Execution Time (seconds)')
    ax1.grid(True, linestyle='--', alpha=0.7)
    
    # Add error bars showing min/max
    for tc in thread_counts:
        min_time = results[tc]["min"]
        max_time = results[tc]["max"]
        ax1.plot([tc, tc], [min_time, max_time], 'b-')
    
    # Plot speedup
    ideal_speedup = [tc for tc in thread_counts]  # Ideal linear speedup
    
    ax2.plot(thread_counts, speedups, 'o-', color='green', label='Actual')
    ax2.plot(thread_counts, ideal_speedup, '--', color='red', alpha=0.7, label='Ideal Linear')
    ax2.set_title('OpenMP Speed-up Factor')
    ax2.set_xlabel('Thread Count')
    ax2.set_ylabel('Speed-up Factor')
    ax2.grid(True, linestyle='--', alpha=0.7)
    ax2.legend()
    
    plt.tight_layout()
    plt.savefig(output_file)
    print(f"Thread scaling plot saved to {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Extract and analyze OpenMP performance metrics')
    parser.add_argument('--mode', choices=['prometheus', 'test', 'report'], default='prometheus',
                        help='Extraction mode: prometheus=extract from metrics, test=run controlled test, report=generate full report')
    parser.add_argument('--image', default='images/test.jpg',
                        help='Image to use for testing (only for test mode)')
    parser.add_argument('--threads', default='1,2,4,6',
                        help='Thread counts to test, comma-separated (only for test mode)')
    parser.add_argument('--repeats', type=int, default=3,
                        help='Number of repeats per thread count (only for test mode)')
    parser.add_argument('--output', default=None,
                        help='Output file for report or plot')
    args = parser.parse_args()
    
    if args.mode == 'prometheus':
        metrics = extract_prometheus_metrics()
        if metrics:
            print("\nOpenMP Processing Time Metrics:")
            print(f"Total executions: {metrics['total_count']}")
            print(f"Average time: {metrics['average_time']:.3f} seconds")
            if "p50" in metrics:
                print(f"Median time: <= {metrics['p50']:.3f} seconds")
            if "p95" in metrics:
                print(f"95th percentile: <= {metrics['p95']:.3f} seconds")
            if "failures" in metrics:
                print(f"Failures: {metrics['failures']}")
        else:
            print("Failed to extract metrics")
            
    elif args.mode == 'test':
        thread_counts = [int(t) for t in args.threads.split(',')]
        results = run_controlled_test(args.image, thread_counts, args.repeats)
        
        if results:
            print("\nThread Scaling Results:")
            if 1 in results:
                base_time = results[1]["mean"]
                print(f"Baseline (1 thread): {base_time:.3f}s")
                
            for tc in sorted(results.keys()):
                res = results[tc]
                speedup = res.get("speedup", 1.0)
                efficiency = speedup / tc if tc > 0 else 1.0
                
                print(f"Threads: {tc}, "
                      f"Time: {res['mean']:.3f}s ({res['min']:.3f}-{res['max']:.3f}), "
                      f"Speedup: {speedup:.2f}x, "
                      f"Efficiency: {efficiency*100:.1f}%")
            
            # Generate plot
            output_file = args.output or "openmp_scaling.png"
            plot_thread_scaling(results, output_file)
            
    elif args.mode == 'report':
        output_file = args.output or "openmp_report.txt"
        generate_report(output_file)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
