#!/usr/bin/env python3
"""Run load tests at various request counts and plot the results.

This script sends multiple image-processing requests to the frontend
and collects both latency metrics and Prometheus statistics from the
frontend and worker. It then generates graphs showing how performance
changes as the number of requests grows.
"""
import argparse
import concurrent.futures
import os
import random
import re
import sys
import time

import matplotlib.pyplot as plt
import requests

# allow importing sibling module
sys.path.append(os.path.dirname(__file__))
from load_test import submit, create_session, check_server_health


METRICS_URL_FRONTEND = os.environ.get('FRONTEND_METRICS', 'http://localhost:8000/metrics')
METRICS_URL_WORKER = os.environ.get('WORKER_METRICS', 'http://localhost:8001/')
RABBIT_MANAGEMENT_URL = os.environ.get('RABBIT_MANAGEMENT_URL', 'http://localhost:15672/api/queues/%2F/grayscale')
RABBIT_USER = os.environ.get('RABBIT_USER', 'guest')
RABBIT_PASS = os.environ.get('RABBIT_PASS', 'guest')


def check_rabbitmq_health(url=RABBIT_MANAGEMENT_URL, user=RABBIT_USER, passwd=RABBIT_PASS, max_messages=100):
    """Check if RabbitMQ is healthy and not overloaded"""
    try:
        response = requests.get(url, auth=(user, passwd), timeout=5)
        if response.status_code != 200:
            return False, f"RabbitMQ returned status code {response.status_code}"
            
        queue_info = response.json()
        messages = queue_info.get('messages', 0)
        
        if messages > max_messages:
            return False, f"RabbitMQ queue has {messages} messages (limit: {max_messages})"
        
        return True, f"RabbitMQ healthy: {messages} messages in queue"
    except Exception as e:
        return False, f"Error checking RabbitMQ: {e}"


def scrape_metrics():
    """Return raw Prometheus metrics for frontend and worker."""
    try:
        session = create_session()
        ftxt = session.get(METRICS_URL_FRONTEND, timeout=5).text
        wtxt = session.get(METRICS_URL_WORKER, timeout=5).text
        return ftxt, wtxt
    except requests.RequestException as e:
        print(f"Error scraping metrics: {e}")
        return "", ""


def hist_values(text, name):
    """Return (sum, count) for a Prometheus histogram."""
    sum_re = re.search(r'^' + re.escape(name) + r'_sum\s+(\S+)', text, re.M)
    cnt_re = re.search(r'^' + re.escape(name) + r'_count\s+(\S+)', text, re.M)
    sum_val = float(sum_re.group(1)) if sum_re else 0.0
    cnt_val = float(cnt_re.group(1)) if cnt_re else 0.0
    return sum_val, cnt_val


def metrics_snapshot():
    ftxt, wtxt = scrape_metrics()
    fs, fc = hist_values(ftxt, 'frontend_request_seconds')
    qs, qc = hist_values(wtxt, 'grayscale_queue_wait_seconds')
    ps, pc = hist_values(wtxt, 'grayscale_process_seconds')
    return {
        'req_sum': fs, 'req_cnt': fc,
        'queue_sum': qs, 'queue_cnt': qc,
        'proc_sum': ps, 'proc_cnt': pc,
    }


def delta_metrics(after, before):
    return {k: after[k] - before.get(k, 0) for k in after}


def run_batch(image, url, count, concurrency, session=None, force_full_concurrency=False, passes=1, threads_list='1,2,4'):
    """Run a batch of requests with circuit breaker pattern to prevent overload"""
    latencies = []
    
    # Scale delay based on request count
    base_delay = 0.5
    if count > 10:
        base_delay = 1.0
    if count > 20:
        base_delay = 1.5
    if count > 50:
        base_delay = 2.0
    
    # Set reasonable timeouts and retries - scale with request count
    timeout = min(60, 30 + (count // 10))
    max_retries = 3
    
    # Use gentler concurrency level for higher request counts unless forced
    if force_full_concurrency:
        actual_concurrency = concurrency
        print("Warning: Using full requested concurrency - this may overload the system!")
    else:
        actual_concurrency = min(concurrency, 5 if count <= 20 else 3)
    
    print(f"Using delay={base_delay}s, concurrency={actual_concurrency}, timeout={timeout}s")
    
    # Create a session for connection pooling if none provided
    if session is None:
        session = create_session()
    
    # Circuit breaker state
    failures = 0
    max_failures = max(3, count // 10)  # Allow more failures for larger batches
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=actual_concurrency) as ex:
        futures = []
        
        # Submit with staggered delays to prevent overloading
        for i in range(count):
            # Check circuit breaker
            if failures >= max_failures:
                print(f"Circuit breaker tripped after {failures} failures. Stopping batch.")
                break
                
            # Add jitter to delay to prevent synchronized bursts
            jitter = random.uniform(0.1, 0.5) if base_delay > 0 else 0
            
            # Check RabbitMQ health every 5 requests for large batches
            if i > 0 and i % 5 == 0 and count > 10:
                rabbit_healthy, msg = check_rabbitmq_health()
                print(f"RabbitMQ check: {msg}")
                
                if not rabbit_healthy:
                    print(f"RabbitMQ appears overloaded. Pausing for recovery...")
                    # Add an extra backoff pause
                    time.sleep(10)
                    
                    # Recheck - if still unhealthy, abort batch
                    rabbit_healthy, msg = check_rabbitmq_health()
                    if not rabbit_healthy:
                        print(f"RabbitMQ still unhealthy. Stopping batch: {msg}")
                        break
            
            futures.append(ex.submit(
                submit, image, url, 
                retry_delay=2, 
                max_retries=max_retries, 
                timeout=timeout,
                session=session,
                passes=passes,
                threads=[int(t) for t in threads_list.split(',')]
            ))
            
            if i < count - 1:  # Don't sleep after last request
                time.sleep(base_delay + jitter)
        
        # Process results as they complete
        for fut in concurrent.futures.as_completed(futures):
            try:
                latency = fut.result()
                latencies.append(latency)
            except Exception as e:
                print(f"Request failed: {e}")
                failures += 1
                
                # If we hit too many failures, break out
                if failures >= max_failures:
                    print(f"Too many failures ({failures}/{max_failures}). Stopping batch.")
                    break
    
    if not latencies:
        print("All requests failed or batch was terminated!")
        return {
            'avg': 0,
            'p95': 0,
            'throughput': 0,
            'success_rate': 0
        }
    
    latencies.sort()
    total = sum(latencies)
    
    # Handle the case where we have very few results
    p95_idx = max(0, int(0.95 * len(latencies)) - 1)
    p95 = latencies[p95_idx] if latencies else 0
    
    return {
        'avg': total / len(latencies),
        'p95': p95,
        'throughput': len(latencies) / total,
        'success_rate': len(latencies) / count
    }


def main():
    parser = argparse.ArgumentParser(description='Benchmark event-driven stack and plot metrics')
    parser.add_argument('image', help='image to upload')
    parser.add_argument('--counts', default='1,10,20,50,100', help='comma separated request counts')
    parser.add_argument('--url', default='http://localhost:8080/', help='frontend URL')
    parser.add_argument('--concurrency', type=int, default=None, help='workers per run (default=count)')
    parser.add_argument('--output', default='benchmark.png', help='output PNG file')
    parser.add_argument('--safer', action='store_true', help='use more conservative test settings')
    parser.add_argument('--force-concurrency', action='store_true', 
                        help='force the use of the full requested concurrency (may overload system)')
    parser.add_argument('--passes', type=int, default=1, help='number of kernel passes (increases computation load)')
    parser.add_argument('--threads', type=str, default='1,2,4', help='comma-separated list of thread counts')
    args = parser.parse_args()
    
    if args.safer:
        print("Using safer test settings with reduced load")
        counts = [1, 5, 10] 
    else:
        counts = [int(c) for c in args.counts.split(',')]
    
    results = []
    
    # Normalize URL
    if not args.url.endswith('/'):
        args.url += '/'
    
    # Test server connection
    healthy, message = check_server_health(args.url)
    print(f"Server health check: {message}")
    if not healthy:
        print("Make sure the server is running before starting the benchmark.")
        return 1
    
    # Create a session for reuse across all batches
    session = create_session()
    
    for c in counts:
        try:
            # Use requested concurrency but cap at 10 unless forced
            if args.force_concurrency:
                conc = args.concurrency or c
            else:
                conc = min(args.concurrency or c, 10)
            
            # Add increasing cooldown delays between tests as counts grow
            if len(results) > 0:
                # Scale cooldown with previous batch size
                prev_count = counts[len(results) - 1]
                cooldown = 5 + (prev_count // 5)
                print(f"Cooling down for {cooldown}s before next batch...")
                time.sleep(cooldown)
                
                # Check RabbitMQ health before proceeding
                rabbit_healthy, msg = check_rabbitmq_health()
                print(f"RabbitMQ check before batch: {msg}")
                
                if not rabbit_healthy:
                    print("RabbitMQ is not healthy. Waiting for recovery...")
                    # Try a longer cooldown
                    time.sleep(20)
                    
                    # Recheck - if still unhealthy, skip this batch
                    rabbit_healthy, msg = check_rabbitmq_health()
                    if not rabbit_healthy:
                        print(f"RabbitMQ still unhealthy - skipping batch with {c} requests")
                        continue
            
            print(f'Running {c} requests with concurrency {conc}, passes={args.passes}, threads={args.threads}')
            before = metrics_snapshot()
            stats = run_batch(args.image, args.url, c, conc, 
                             session=session, 
                             force_full_concurrency=args.force_concurrency,
                             passes=args.passes,
                             threads_list=args.threads)
            after = metrics_snapshot()
            
            diff = delta_metrics(after, before)
            req_avg = diff['req_sum'] / diff['req_cnt'] if diff['req_cnt'] else 0
            queue_avg = diff['queue_sum'] / diff['queue_cnt'] if diff['queue_cnt'] else 0
            proc_avg = diff['proc_sum'] / diff['proc_cnt'] if diff['proc_cnt'] else 0
            
            # Check if batch had meaningful results
            if stats['success_rate'] < 0.5:
                print(f"Warning: Low success rate ({stats['success_rate']*100:.1f}%) - metrics may be unreliable")
                
                if stats['success_rate'] == 0:
                    print(f"Batch with {c} requests failed completely - skipping results")
                    continue
            
            results.append({
                'count': c,
                'lat_avg': stats['avg'],
                'lat_p95': stats['p95'],
                'throughput': stats['throughput'],
                'queue_avg': queue_avg,
                'proc_avg': proc_avg,
                'req_avg': req_avg,
                'success_rate': stats.get('success_rate', 1.0),
            })
            
            print(f'Average latency: {stats["avg"]:.3f}s')
            print(f'95th percentile: {stats["p95"]:.3f}s')
            print(f'Throughput: {stats["throughput"]:.2f} req/s')
            if 'success_rate' in stats:
                print(f'Success rate: {stats["success_rate"]*100:.1f}%')
        except Exception as e:
            print(f"Error during batch with {c} requests: {e}")
            print("Continuing with next batch...")

    # Check if we have any results
    if not results:
        print("No successful batches completed. Cannot generate plot.")
        return 1
    
    try:
        # plotting
        counts = [r['count'] for r in results]
        fig, axes = plt.subplots(2, 2, figsize=(10, 8))

        axes[0, 0].plot(counts, [r['lat_avg'] for r in results], marker='o')
        axes[0, 0].set_title('Average latency')
        axes[0, 0].set_xlabel('Requests')
        axes[0, 0].set_ylabel('Seconds')

        axes[0, 1].plot(counts, [r['lat_p95'] for r in results], marker='o', color='orange')
        axes[0, 1].set_title('95th percentile latency')
        axes[0, 1].set_xlabel('Requests')
        axes[0, 1].set_ylabel('Seconds')

        axes[1, 0].plot(counts, [r['throughput'] for r in results], marker='o', color='green')
        axes[1, 0].set_title('Throughput')
        axes[1, 0].set_xlabel('Requests')
        axes[1, 0].set_ylabel('req/s')

        # Add success rate to one of the plots
        ax2 = axes[1, 0].twinx()
        ax2.plot(counts, [r['success_rate']*100 for r in results], marker='x', color='red', linestyle='--')
        ax2.set_ylabel('Success rate %', color='red')
        ax2.tick_params(axis='y', labelcolor='red')

        axes[1, 1].plot(counts, [r['queue_avg'] for r in results], marker='o', label='Queue wait')
        axes[1, 1].plot(counts, [r['proc_avg'] for r in results], marker='o', label='Processing')
        axes[1, 1].plot(counts, [r['req_avg'] for r in results], marker='o', label='Total request')
        axes[1, 1].set_title('Prometheus averages')
        axes[1, 1].set_xlabel('Requests')
        axes[1, 1].set_ylabel('Seconds')
        axes[1, 1].legend()

        fig.tight_layout()
        plt.savefig(args.output)
        print(f'Saved plot to {args.output}')
        
    except Exception as e:
        print(f"Error generating plot: {e}")
        return 1
        
    return 0


if __name__ == '__main__':
    sys.exit(main())
