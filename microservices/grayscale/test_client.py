import sys
import time
import requests

USAGE = "usage: python3 test_client.py <input_img> [output_img] [--threads=N] [--passes=N] [--url=http://localhost:5000]"

def parse_args(argv):
    input_path = None
    output_path = 'out.png'
    url = 'http://localhost:5000'
    threads = None
    passes = None
    for arg in argv[1:]:
        if arg.startswith('--threads='):
            threads = arg.split('=',1)[1]
        elif arg.startswith('--passes='):
            passes = arg.split('=',1)[1]
        elif arg.startswith('--url='):
            url = arg.split('=',1)[1]
        elif input_path is None:
            input_path = arg
        elif output_path == 'out.png':
            output_path = arg
        else:
            print(USAGE)
            sys.exit(1)
    if not input_path:
        print(USAGE)
        sys.exit(1)
    return input_path, output_path, url, threads, passes

def main(argv):
    input_path, output_path, url, threads, passes = parse_args(argv)
    files = {'image': open(input_path,'rb')}
    data = {}
    if threads:
        data['threads'] = threads
    if passes:
        data['passes'] = passes
    t0 = time.time()
    r = requests.post(f"{url}/grayscale", files=files, data=data)
    elapsed = time.time() - t0
    if r.ok:
        with open(output_path, 'wb') as f:
            f.write(r.content)
        print(f"Saved grayscale image to {output_path}")
        print(f"Request time: {elapsed:.3f}s")
        if 'X-Elapsed' in r.headers:
            print(f"Service processing time: {r.headers['X-Elapsed']}s")
    else:
        print(f"Error {r.status_code}: {r.text}")
        print(f"Request time: {elapsed:.3f}s")

if __name__ == '__main__':
    main(sys.argv)
