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
import re
import sys
import time

import matplotlib.pyplot as plt
import requests

# allow importing sibling module
sys.path.append(os.path.dirname(__file__))
from load_test import submit


METRICS_URL_FRONTEND = os.environ.get('FRONTEND_METRICS', 'http://localhost:8000/metrics')
METRICS_URL_WORKER = os.environ.get('WORKER_METRICS', 'http://localhost:8001/')


def scrape_metrics():
    """Return raw Prometheus metrics for frontend and worker."""
    ftxt = requests.get(METRICS_URL_FRONTEND).text
    wtxt = requests.get(METRICS_URL_WORKER).text
    return ftxt, wtxt


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


def run_batch(image, url, count, concurrency):
    latencies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(submit, image, url) for _ in range(count)]
        for fut in concurrent.futures.as_completed(futures):
            latencies.append(fut.result())
    latencies.sort()
    total = sum(latencies)
    p95 = latencies[int(0.95 * len(latencies)) - 1]
    return {
        'avg': total / len(latencies),
        'p95': p95,
        'throughput': len(latencies) / total,
    }


def main():
    parser = argparse.ArgumentParser(description='Benchmark event-driven stack and plot metrics')
    parser.add_argument('image', help='image to upload')
    parser.add_argument('--counts', default='1,10,20,50,100', help='comma separated request counts')
    parser.add_argument('--url', default='http://localhost:8080/', help='frontend URL')
    parser.add_argument('--concurrency', type=int, default=None, help='workers per run (default=count)')
    parser.add_argument('--output', default='benchmark.png', help='output PNG file')
    args = parser.parse_args()

    counts = [int(c) for c in args.counts.split(',')]
    results = []
    for c in counts:
        conc = args.concurrency or c
        print(f'Running {c} requests with concurrency {conc}')
        before = metrics_snapshot()
        stats = run_batch(args.image, args.url, c, conc)
        after = metrics_snapshot()
        diff = delta_metrics(after, before)
        req_avg = diff['req_sum'] / diff['req_cnt'] if diff['req_cnt'] else 0
        queue_avg = diff['queue_sum'] / diff['queue_cnt'] if diff['queue_cnt'] else 0
        proc_avg = diff['proc_sum'] / diff['proc_cnt'] if diff['proc_cnt'] else 0
        results.append({
            'count': c,
            'lat_avg': stats['avg'],
            'lat_p95': stats['p95'],
            'throughput': stats['throughput'],
            'queue_avg': queue_avg,
            'proc_avg': proc_avg,
            'req_avg': req_avg,
        })

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


if __name__ == '__main__':
    main()

