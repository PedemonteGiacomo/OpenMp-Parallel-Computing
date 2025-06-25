import io
import json
import os
import subprocess
import tempfile
import time

from prometheus_client import Histogram, Counter, start_http_server

from minio import Minio
import pika

BUCKET = 'images'
BINARY_PATH = os.path.join(os.path.dirname(__file__), 'bin', 'grayscale')

# Prometheus metrics
QUEUE_WAIT = Histogram(
    'grayscale_queue_wait_seconds',
    'Time a message spent waiting in the queue before being processed'
)
PROCESS_TIME = Histogram(
    'grayscale_process_seconds',
    'Time spent executing the grayscale algorithm'
)
STARTUP_TIME = Histogram(
    'grayscale_startup_seconds',
    'Time from container start to first processed message'
)
FAILURES = Counter('grayscale_failures_total', 'Number of processing failures')

_start_time = time.time()
_first_message = True

minio_client = Minio(
    os.environ.get('MINIO_ENDPOINT', 'minio:9000'),
    access_key=os.environ.get('MINIO_ACCESS_KEY', 'minioadmin'),
    secret_key=os.environ.get('MINIO_SECRET_KEY', 'minioadmin'),
    secure=False,
)

if not minio_client.bucket_exists(BUCKET):
    minio_client.make_bucket(BUCKET)

def connect_rabbitmq(url: str, retries: int = 10, delay: int = 5):
    for i in range(retries):
        try:
            return pika.BlockingConnection(pika.URLParameters(url))
        except pika.exceptions.AMQPConnectionError:
            print(f"Waiting for RabbitMQ... ({i + 1}/{retries})")
            time.sleep(delay)
    raise RuntimeError("Could not connect to RabbitMQ")

connection = connect_rabbitmq(os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/'))
channel = connection.channel()
channel.queue_declare(queue='grayscale')
channel.queue_declare(queue='grayscale_processed')

# start metrics HTTP server
start_http_server(8001)

def process(ch, method, properties, body):
    msg = json.loads(body)
    image_key = msg['image_key']
    threads = msg.get('threads') or [1]
    if isinstance(threads, int):
        threads = [threads]
    passes = msg.get('passes')
    repeats = int(msg.get('repeat', 1))

    global _first_message
    if _first_message:
        STARTUP_TIME.observe(time.time() - _start_time)
        _first_message = False

    sent_ts = msg.get('sent_ts')
    if sent_ts:
        QUEUE_WAIT.observe(time.time() - sent_ts)
    try:
        resp = minio_client.get_object(BUCKET, image_key)
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, os.path.basename(image_key))
            with open(in_path, 'wb') as f:
                for d in resp.stream(32 * 1024):
                    f.write(d)
            out_path = os.path.join(tmpdir, 'out.png')
            times = {}
            for t in threads:
                env = os.environ.copy()
                env['OMP_NUM_THREADS'] = str(t)
                single = []
                for _ in range(repeats):
                    cmd = [BINARY_PATH, in_path, out_path]
                    if passes:
                        cmd.append(str(passes))
                    start_proc = time.time()
                    subprocess.run(cmd, check=True, env=env)
                    elapsed = time.time() - start_proc
                    PROCESS_TIME.observe(elapsed)
                    single.append(elapsed)
                times[str(t)] = sum(single) / len(single)

            with open(out_path, 'rb') as outf:
                data = outf.read()
    except Exception:
        FAILURES.inc()
        ch.basic_ack(delivery_tag=method.delivery_tag)
        raise

    processed_key = f"processed/{os.path.basename(image_key)}"
    minio_client.put_object(
        BUCKET,
        processed_key,
        io.BytesIO(data),
        length=len(data),
        content_type='image/png',
    )

    payload = {
        'image_key': image_key,
        'processed_key': processed_key,
        'times': times,
        'passes': passes,
    }
    channel.basic_publish(
        exchange='',
        routing_key='grayscale_processed',
        body=json.dumps(payload).encode(),
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(queue='grayscale', on_message_callback=process)
print(' [*] Waiting for messages. To exit press CTRL+C')
channel.start_consuming()
