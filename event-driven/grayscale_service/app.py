import io
import json
import os
import subprocess
import tempfile
import time

from minio import Minio
import pika

BUCKET = 'images'
BINARY_PATH = os.path.join(os.path.dirname(__file__), 'bin', 'grayscale')

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

def process(ch, method, properties, body):
    msg = json.loads(body)
    image_key = msg['image_key']
    threads = msg.get('threads') or [1]
    if isinstance(threads, int):
        threads = [threads]
    passes = msg.get('passes')
    repeats = int(msg.get('repeat', 1))
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
                start = time.time()
                subprocess.run(cmd, check=True, env=env)
                single.append(time.time() - start)
            times[str(t)] = sum(single) / len(single)

        with open(out_path, 'rb') as outf:
            data = outf.read()

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
        subprocess.run([BINARY_PATH, in_path, out_path], check=True)
        with open(out_path, 'rb') as outf:
            data = outf.read()
    processed_key = f"processed/{os.path.basename(image_key)}"
    minio_client.put_object(BUCKET, processed_key, io.BytesIO(data), length=len(data), content_type='image/png')
    channel.basic_publish(
        '',
        'grayscale_processed',
        json.dumps({'image_key': image_key, 'processed_key': processed_key}).encode(),
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(queue='grayscale', on_message_callback=process)
print(' [*] Waiting for messages. To exit press CTRL+C')
channel.start_consuming()
