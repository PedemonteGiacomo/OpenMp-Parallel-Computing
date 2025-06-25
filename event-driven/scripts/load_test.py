#!/usr/bin/env python3
import argparse
import concurrent.futures
import os
import random
import re
import sys
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_session(retries=3):
    """
    Create a requests session with automatic retries for GET requests
    and connection pooling.
    """
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy, 
        pool_connections=20, 
        pool_maxsize=20
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def submit(image_path, url, retry_delay=2, max_retries=3, timeout=30, session=None):
    """
    Submit an image for processing with rate limiting and retries.
    
    Args:
        image_path: Path to the image file
        url: Base URL of the frontend service
        retry_delay: Seconds to wait between retries
        max_retries: Maximum number of retry attempts
        timeout: Maximum seconds to wait for processing
        session: Reusable requests session (optional)
    """
    start = time.time()
    retry_count = 0
    
    # Use provided session or create a new one
    if session is None:
        session = create_session()
    
    while retry_count <= max_retries:
        try:
            # Determine image MIME type based on extension
            if image_path.lower().endswith('.jpg') or image_path.lower().endswith('.jpeg'):
                mime_type = 'image/jpeg'
            elif image_path.lower().endswith('.png'):
                mime_type = 'image/png'
            else:
                mime_type = 'image/jpeg'  # Default to JPEG
                
            # Print debug information
            print(f"Submitting request to {url} with image {image_path}")
            
            # Add thread selection and repeat parameters
            # Only test with 1-2 threads to reduce system load
            data = {'threads': [1], 'repeat': 1}
            
            with open(image_path, 'rb') as f:
                files = {'image': (os.path.basename(image_path), f, mime_type)}
                resp = session.post(url, files=files, data=data, timeout=(5, 30))
            
            # Print response status for debugging
            print(f"Response status: {resp.status_code}")
            
            if resp.status_code != 200:
                raise requests.HTTPError(f"Server error response: {resp.text[:200]}")
                
            # Extract the key from the response
            m = re.search(r'/status\?key=([^"\']+)', resp.text)
            if not m:
                print("Response content (truncated):", resp.text[:200])
                raise RuntimeError('Key not found in response')
            
            key = m.group(1)
            print(f"Got key: {key}, waiting for processing")
            
            # Poll for results with timeout
            start_poll = time.time()
            poll_count = 0
            
            while time.time() - start_poll < timeout:
                try:
                    st = session.get(f"{url}status", params={'key': key}, timeout=5)
                    st.raise_for_status()
                    data = st.json()
                    
                    if data.get('processed'):
                        print(f"Processing complete for key {key}")
                        return time.time() - start
                        
                    # Print a progress dot every few polls
                    poll_count += 1
                    if poll_count % 3 == 0:
                        print(".", end="", flush=True)
                        
                    # Gradually increase polling interval if taking a while
                    sleep_time = min(0.5 + (poll_count * 0.1), 2.0)
                    time.sleep(sleep_time)
                    
                except requests.RequestException as e:
                    print(f"Error polling status: {e}")
                    time.sleep(1)  # Wait before retrying poll
            
            print(f"\nTimeout waiting for processing of key {key}")
            return time.time() - start
            
        except (requests.RequestException, RuntimeError) as e:
            retry_count += 1
            delay = retry_delay * (2 ** (retry_count - 1))  # Exponential backoff
            
            print(f"Error during submission (attempt {retry_count}/{max_retries}): {type(e).__name__}: {e}")
            
            if retry_count <= max_retries:
                print(f"Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print(f"Max retries reached. Giving up on this request.")
                raise
    
    raise RuntimeError("Failed to submit image after retries")


def check_server_health(url, timeout=5):
    """Check if the server is responsive and report status"""
    try:
        session = create_session()
        resp = session.get(url, timeout=timeout)
        if resp.status_code == 200:
            return True, f"Server is responding normally (status {resp.status_code})"
        else:
            return False, f"Server returned unexpected status code: {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Connection refused - server may be down"
    except requests.exceptions.Timeout:
        return False, "Connection timed out - server may be overloaded"
    except requests.exceptions.RequestException as e:
        return False, f"Error connecting to server: {e}"


def main():
    parser = argparse.ArgumentParser(description='Simple load test for frontend')
    parser.add_argument('image', help='image to upload')
    parser.add_argument('--count', type=int, default=1, help='number of requests')
    parser.add_argument('--concurrency', type=int, default=1, help='parallel workers')
    parser.add_argument('--url', default='http://localhost:8080/', help='frontend URL')
    parser.add_argument('--delay', type=float, default=0.5, help='delay between requests in seconds')
    parser.add_argument('--timeout', type=int, default=60, help='timeout for request processing in seconds')
    parser.add_argument('--retries', type=int, default=3, help='max retries per request')
    parser.add_argument('--debug', action='store_true', help='print detailed debug information')
    args = parser.parse_args()
    
    # Check if image file exists
    if not os.path.isfile(args.image):
        print(f"Error: Image file not found: {args.image}")
        return 1
        
    # Normalize URL
    if not args.url.endswith('/'):
        args.url += '/'
    
    print(f"\nRunning load test with:")
    print(f"- Image: {args.image}")
    print(f"- URL: {args.url}")
    print(f"- Count: {args.count} requests")
    print(f"- Concurrency: {args.concurrency} workers")
    print(f"- Request delay: {args.delay} seconds")
    print(f"- Timeout: {args.timeout} seconds\n")
    
    # Test connection to server before starting
    healthy, message = check_server_health(args.url)
    print(f"Server health check: {message}")
    if not healthy:
        print("Make sure the server is running and accessible before starting the load test.")
        return 1
    
    print("Starting load test...\n")
    
    latencies = []
    failed = 0
    
    # Create a shared session for connection pooling
    session = create_session()
    
    # Create a rate-limited pool of workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = []
        
        # Submit tasks with delay between them
        for i in range(args.count):
            # Add jitter to delay to prevent synchronized bursts
            jitter = random.uniform(0.1, 0.5) if args.delay > 0 else 0
            futures.append(ex.submit(submit, 
                                    args.image, 
                                    args.url, 
                                    retry_delay=2, 
                                    max_retries=args.retries, 
                                    timeout=args.timeout,
                                    session=session))
            
            if i < args.count - 1:  # Don't sleep after the last submission
                time.sleep(args.delay + jitter)
        
        # Process results
        for i, fut in enumerate(concurrent.futures.as_completed(futures)):
            try:
                latency = fut.result()
                latencies.append(latency)
                if args.debug:
                    print(f"Request {i+1}/{args.count} completed in {latency:.3f}s")
            except Exception as e:
                failed += 1
                print(f"Request failed: {e}")
    
    if not latencies:
        print("\nAll requests failed. Check server logs for more information.")
        return 1
        
    print("\nTest complete!")
    print(f"Successful: {len(latencies)}/{args.count} requests")
    if failed > 0:
        print(f"Failed: {failed}/{args.count} requests")
    
    latencies.sort()
    total = sum(latencies)
    
    print("\n--- Results ---")
    print(f"Average latency: {total/len(latencies):.3f}s")
    
    if len(latencies) >= 20:
        p95 = latencies[int(0.95 * len(latencies))]
        p50 = latencies[int(0.50 * len(latencies))]
        print(f"Median latency: {p50:.3f}s")
        print(f"95th percentile: {p95:.3f}s")
    
    print(f"Throughput: {len(latencies)/total:.2f} req/s")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
