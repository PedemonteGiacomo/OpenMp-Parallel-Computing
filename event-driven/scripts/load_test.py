#!/usr/bin/env python3
import argparse
import concurrent.futures
import re
import time
import requests


def submit(image_path, url):
    start = time.time()
    with open(image_path, 'rb') as f:
        files = {'image': (image_path, f, 'image/jpeg')}
        resp = requests.post(url, files=files)
    resp.raise_for_status()
    m = re.search(r'/status\?key=([^"\']+)', resp.text)
    if not m:
        raise RuntimeError('Key not found in response')
    key = m.group(1)
    while True:
        st = requests.get(f"{url}status", params={'key': key})
        st.raise_for_status()
        data = st.json()
        if data.get('processed'):
            break
        time.sleep(0.5)
    return time.time() - start


def main():
    parser = argparse.ArgumentParser(description='Simple load test for frontend')
    parser.add_argument('image', help='image to upload')
    parser.add_argument('--count', type=int, default=1, help='number of requests')
    parser.add_argument('--concurrency', type=int, default=1, help='parallel workers')
    parser.add_argument('--url', default='http://localhost:8080/', help='frontend URL')
    args = parser.parse_args()

    latencies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = [ex.submit(submit, args.image, args.url) for _ in range(args.count)]
        for fut in concurrent.futures.as_completed(futures):
            latencies.append(fut.result())

    latencies.sort()
    total = sum(latencies)
    p95 = latencies[int(0.95 * len(latencies)) - 1]
    print(f"Completed {len(latencies)} requests")
    print(f"Average latency: {total/len(latencies):.3f}s")
    print(f"95th percentile: {p95:.3f}s")
    print(f"Throughput: {len(latencies)/total:.2f} req/s")


if __name__ == '__main__':
    main()
