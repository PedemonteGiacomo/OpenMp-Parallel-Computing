import io
import json
import os
import subprocess
import tempfile
import time
import sys
import logging

from prometheus_client import Histogram, Counter, start_http_server

from minio import Minio
import pika
from pika.exceptions import AMQPConnectionError, AMQPChannelError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("grayscale_service")

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
RECONNECT_ATTEMPTS = Counter('grayscale_reconnect_attempts', 'Number of RabbitMQ reconnection attempts')

_start_time = time.time()
_first_message = True

# Connection parameters
MAX_RECONNECT_ATTEMPTS = 10
RECONNECT_DELAY = 5
PREFETCH_COUNT = int(os.environ.get('PREFETCH_COUNT', 1))  # Only process one message at a time by default

minio_client = Minio(
    os.environ.get('MINIO_ENDPOINT', 'minio:9000'),
    access_key=os.environ.get('MINIO_ACCESS_KEY', 'minioadmin'),
    secret_key=os.environ.get('MINIO_SECRET_KEY', 'minioadmin'),
    secure=False,
)

# Make sure bucket exists
try:
    if not minio_client.bucket_exists(BUCKET):
        minio_client.make_bucket(BUCKET)
        logger.info(f"Created bucket: {BUCKET}")
    else:
        logger.info(f"Bucket {BUCKET} already exists")
except Exception as e:
    logger.error(f"Error checking/creating Minio bucket: {e}")
    # Continue anyway, we'll fail later if needed

def connect_rabbitmq(url: str, retries: int = 10, delay: int = 5):
    for i in range(retries):
        try:
            connection = pika.BlockingConnection(pika.URLParameters(url))
            logger.info("Successfully connected to RabbitMQ")
            return connection
        except AMQPConnectionError:
            logger.warning(f"Waiting for RabbitMQ... ({i + 1}/{retries})")
            RECONNECT_ATTEMPTS.inc()
            time.sleep(delay)
    raise RuntimeError("Could not connect to RabbitMQ after multiple retries")

# Get RabbitMQ URL from environment, with fallback
rabbitmq_url = os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/')
connection = connect_rabbitmq(rabbitmq_url, MAX_RECONNECT_ATTEMPTS, RECONNECT_DELAY)
channel = connection.channel()

# Declare queues - make sure they're durable
channel.queue_declare(queue='grayscale', durable=True)
channel.queue_declare(queue='grayscale_processed', durable=True)

# Set prefetch count to control how many messages we process at once
# This prevents the service from being overwhelmed
channel.basic_qos(prefetch_count=PREFETCH_COUNT)

# Start metrics HTTP server
start_http_server(8001)
logger.info("Metrics server started on port 8001")

def process(ch, method, properties, body):
    """Process a grayscale conversion request"""
    start_process_time = time.time()
    
    try:
        msg = json.loads(body)
        image_key = msg['image_key']
        threads = msg.get('threads') or [1]
        if isinstance(threads, int):
            threads = [threads]
        passes = msg.get('passes')
        repeats = int(msg.get('repeat', 1))

        logger.info(f"Processing image {image_key} with threads={threads}, repeats={repeats}")

        global _first_message
        if _first_message:
            STARTUP_TIME.observe(time.time() - _start_time)
            _first_message = False

        sent_ts = msg.get('sent_ts')
        if sent_ts:
            queue_wait_time = time.time() - sent_ts
            QUEUE_WAIT.observe(queue_wait_time)
            logger.info(f"Message waited in queue for {queue_wait_time:.2f}s")

        # Get the image from Minio
        try:
            resp = minio_client.get_object(BUCKET, image_key)
            with tempfile.TemporaryDirectory() as tmpdir:
                in_path = os.path.join(tmpdir, os.path.basename(image_key))
                with open(in_path, 'wb') as f:
                    for d in resp.stream(32 * 1024):
                        f.write(d)
                
                logger.info(f"Downloaded image {image_key} to {in_path}")
                out_path = os.path.join(tmpdir, 'out.png')
                times = {}
                
                for t in threads:
                    env = os.environ.copy()
                    env['OMP_NUM_THREADS'] = str(t)
                    single = []
                    
                    for i in range(repeats):
                        cmd = [BINARY_PATH, in_path, out_path]
                        if passes:
                            cmd.append(str(passes))
                            
                        logger.info(f"Running {' '.join(cmd)} (thread={t}, run {i+1}/{repeats})")
                        start_proc = time.time()
                        
                        try:
                            subprocess.run(cmd, check=True, env=env)
                            elapsed = time.time() - start_proc
                            PROCESS_TIME.observe(elapsed)
                            single.append(elapsed)
                            logger.info(f"Processing time: {elapsed:.2f}s for thread={t}, run {i+1}")
                        except subprocess.CalledProcessError as e:
                            logger.error(f"Error processing image: {e}")
                            FAILURES.inc()
                            # Continue with other runs, we'll use whatever data we have
                    
                    # Calculate average time if we have any successful runs
                    if single:
                        times[str(t)] = sum(single) / len(single)
                
                # If we have no successful runs at all, raise exception
                if not times:
                    raise RuntimeError("All processing runs failed")

                with open(out_path, 'rb') as outf:
                    data = outf.read()
                    
                logger.info(f"Successfully processed image, size: {len(data)} bytes")
                
                # Save processed image back to Minio
                processed_key = f"processed/{os.path.basename(image_key)}"
                minio_client.put_object(
                    BUCKET,
                    processed_key,
                    io.BytesIO(data),
                    length=len(data),
                    content_type='image/png',
                )
                
                logger.info(f"Uploaded processed image to {processed_key}")

                # Send completion message
                payload = {
                    'image_key': image_key,
                    'processed_key': processed_key,
                    'times': times,
                    'passes': passes,
                    'process_time': time.time() - start_process_time
                }
                
                # Use delivery mode 2 for persistent messages
                properties = pika.BasicProperties(
                    delivery_mode=2,  # make message persistent
                )
                
                channel.basic_publish(
                    exchange='',
                    routing_key='grayscale_processed',
                    body=json.dumps(payload).encode(),
                    properties=properties
                )
                
                logger.info(f"Published completion message for {image_key}")
        
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            FAILURES.inc()
            raise
            
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        FAILURES.inc()
    finally:
        # Always acknowledge message to avoid getting stuck
        # Even if processing fails, we don't want to reprocess the same message
        ch.basic_ack(delivery_tag=method.delivery_tag)

def main():
    """Main function with reconnection handling"""
    try:
        logger.info(f"Starting grayscale service with prefetch_count={PREFETCH_COUNT}")
        channel.basic_consume(queue='grayscale', on_message_callback=process)
        logger.info('Waiting for messages. To exit press CTRL+C')
        channel.start_consuming()
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully")
        channel.stop_consuming()
        connection.close()
    except (AMQPConnectionError, AMQPChannelError) as e:
        logger.error(f"RabbitMQ connection error: {e}")
        logger.info("Attempting to reconnect...")
        time.sleep(5)
        # Properly exit so container can restart
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
