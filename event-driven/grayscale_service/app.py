import io
import json
import os
import subprocess
import tempfile
import time
import sys
import logging
import uuid
import re
import threading
import psutil
import random
import random

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
KERNEL_TIME = Histogram(
    'grayscale_kernel_seconds',
    'Time spent in the OpenMP kernel executing the core grayscale algorithm'
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

# Make sure bucket exists - with retries
def ensure_minio_bucket(client, bucket_name, retries=10, delay=5):
    """Ensure that the specified MinIO bucket exists, with retries"""
    for i in range(retries):
        try:
            if not client.bucket_exists(bucket_name):
                client.make_bucket(bucket_name)
                logger.info(f"Created bucket: {bucket_name}")
            else:
                logger.info(f"Bucket {bucket_name} already exists")
            return True
        except Exception as e:
            logger.warning(f"Error checking/creating MinIO bucket (attempt {i+1}/{retries}): {e}")
            time.sleep(delay)
    logger.error("Failed to connect to MinIO after multiple retries")
    return False

# Try to ensure the bucket exists
ensure_minio_bucket(minio_client, BUCKET)

# Setup a heartbeat thread to ensure we respond even when the main thread is busy with processing
def start_heartbeat_thread(connection, interval=30):
    """Start a separate thread to process heartbeats and keep the connection alive"""
    # Keep a reference to the connection object to check if it's been replaced
    connection_ref = connection
    
    def heartbeat_thread_func():
        nonlocal connection_ref
        
        while True:
            try:
                # Process heartbeats more frequently
                time.sleep(interval)
                
                # First check if connection is None or has been garbage collected
                if connection_ref is None:
                    logger.warning("Connection reference is None, heartbeat thread exiting")
                    break
                
                # Now safely check if it's open
                try:
                    if connection_ref.is_open:
                        # Use a short timeout to prevent blocking
                        connection_ref.process_data_events(time_limit=1.0)
                        logger.debug("Heartbeat processed")
                    else:
                        logger.warning("Connection closed, heartbeat thread exiting")
                        break
                except (AttributeError, pika.exceptions.ConnectionWrongStateError):
                    # Connection object was destroyed or is in wrong state
                    logger.warning("Connection invalid or in wrong state, heartbeat thread exiting")
                    break
                    
            except pika.exceptions.ConnectionClosed as e:
                logger.error(f"Connection closed in heartbeat thread: {e}")
                break
            except pika.exceptions.AMQPError as e:
                logger.error(f"AMQP error in heartbeat thread: {e}")
                # For AMQP errors, we should exit and let reconnection logic handle it
                break
            except Exception as e:
                logger.error(f"Error in heartbeat thread: {e}")
                # Don't break for other errors - keep trying but with a backoff
                time.sleep(5)
    
    thread = threading.Thread(target=heartbeat_thread_func, daemon=True)
    thread.start()
    logger.info("Started heartbeat thread")
    return thread

def connect_rabbitmq(url: str, retries: int = 10, delay: int = 5):
    heartbeat_thread = None
    
    for i in range(retries):
        try:
            params = pika.URLParameters(url)
            # Adjust timeout settings for better stability
            params.heartbeat = 30  # 30 seconds - shorter heartbeat for more reliable detection
            params.socket_timeout = 300  # 5 minutes to handle long-running tasks
            params.blocked_connection_timeout = 300  # 5 minutes
            params.tcp_options = {
                'TCP_NODELAY': True,  # Disable Nagle's algorithm for lower latency
            }
            
            # Connect with heartbeat - use a retry pattern for robustness
            try:
                connection = pika.BlockingConnection(params)
            except pika.exceptions.AMQPConnectionError as conn_err:
                logger.warning(f"Connection attempt {i+1} failed: {conn_err}")
                if i == retries - 1:  # Last attempt
                    raise
                time.sleep(delay)
                continue
                
            # Successfully connected - start heartbeat thread
            heartbeat_thread = start_heartbeat_thread(connection, interval=15)  # Process events every 15 seconds
            
            logger.info("Successfully connected to RabbitMQ with heartbeat=%s seconds", params.heartbeat)
            return connection
        except AMQPConnectionError as e:
            logger.warning(f"Waiting for RabbitMQ... ({i + 1}/{retries}): {e}")
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
        # Check if connection is still alive
        if not connection.is_open:
            logger.warning("RabbitMQ connection is closed. Attempting to reconnect...")
            if not handle_rabbitmq_failure():
                raise RuntimeError("Failed to reconnect to RabbitMQ")
                
        msg = json.loads(body)
        image_key = msg['image_key']
        threads = msg.get('threads') or [1]
        if isinstance(threads, int):
            threads = [threads]
        passes = msg.get('passes', 1)
        repeats = int(msg.get('repeat', 1))
        
        # Log more detailed processing information
        active_consumers = PREFETCH_COUNT
        queue_depth = msg.get('queue_depth', 'unknown')
        request_id = msg.get('request_id', str(uuid.uuid4())[:8])
        
        logger.info(f"[REQUEST {request_id}] Processing image {image_key} - threads={threads}, passes={passes}, repeats={repeats}, active_consumers={active_consumers}, queue_depth={queue_depth}")

        global _first_message
        if _first_message:
            STARTUP_TIME.observe(time.time() - _start_time)
            _first_message = False

        sent_ts = msg.get('sent_ts')
        if sent_ts:
            queue_wait_time = time.time() - sent_ts
            QUEUE_WAIT.observe(queue_wait_time)
            logger.info(f"Message waited in queue for {queue_wait_time:.2f}s")

        # Get the image from Minio with retries
        def get_minio_object(bucket, key, retries=5, delay=2):
            """Get an object from MinIO with retries"""
            last_error = None
            for attempt in range(retries):
                try:
                    return minio_client.get_object(bucket, key)
                except Exception as e:
                    last_error = e
                    logger.warning(f"Error getting object from MinIO (attempt {attempt+1}/{retries}): {e}")
                    time.sleep(delay)
            raise last_error or RuntimeError("Failed to get object from MinIO")

        try:
            resp = get_minio_object(BUCKET, image_key)
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
                        
                        # Set thread count in environment
                        start_proc = time.time()
                        
                        # Get system resource info for logging
                        try:
                            import psutil
                            cpu_percent = psutil.cpu_percent(interval=0.1)
                            mem_percent = psutil.virtual_memory().percent
                            system_info = f"CPU: {cpu_percent}%, MEM: {mem_percent}%"
                        except ImportError:
                            system_info = "psutil not available"
                            
                        logger.info(f"Running {' '.join(cmd)} (thread={t}, run {i+1}/{repeats}, passes={passes}, system={system_info})")
                        start_proc = time.time()
                        
                        try:
                            proc = subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
                            proc_output = proc.stdout or ""
                            elapsed = time.time() - start_proc
                            PROCESS_TIME.observe(elapsed)
                            single.append(elapsed)
                            
                            # Parse more detailed output
                            proc_time_match = re.search(r'Compute kernel ×(\d+): ([\d\.]+) s \(threads: (\d+)\)', proc_output)
                            
                            if proc_time_match:
                                actual_passes = int(proc_time_match.group(1))
                                kernel_time = float(proc_time_match.group(2))
                                actual_threads = int(proc_time_match.group(3))
                                
                                # Record kernel time in Prometheus metrics separately
                                KERNEL_TIME.observe(kernel_time)
                                
                                # Store the kernel time as well for later use
                                if str(t) not in times:
                                    times[str(t)] = {'total': [], 'kernel': []}
                                times[str(t)]['total'].append(elapsed)
                                times[str(t)]['kernel'].append(kernel_time)
                                
                                # Calculate overhead percentage
                                overhead = elapsed - kernel_time
                                overhead_pct = (overhead / elapsed) * 100 if elapsed > 0 else 0
                                
                                # We don't have direct access to image dimensions here
                                # Just log what we know without dimensions
                                logger.info(f"Thread {t}, run {i+1}/{repeats} - Kernel time: {kernel_time:.4f}s, " + 
                                          f"total time: {elapsed:.4f}s, overhead: {overhead:.4f}s ({overhead_pct:.1f}%), " +
                                          f"passes={actual_passes}")
                            else:
                                # If we can't parse kernel time, just store total time
                                if str(t) not in times:
                                    times[str(t)] = {'total': [], 'kernel': []}
                                times[str(t)]['total'].append(elapsed)
                        except subprocess.CalledProcessError as e:
                            logger.error(f"Error processing image: {e}")
                            FAILURES.inc()
                            # Continue with other runs, we'll use whatever data we have
                    
                    # Calculate average times - we'll handle this at the end
                
                # If we have no successful runs at all, raise exception
                if not times:
                    raise RuntimeError("All processing runs failed")
                
                # Calculate average times for each thread count
                avg_times = {}
                for t_str, time_data in times.items():
                    # Calculate average total time
                    if time_data['total']:
                        avg_total = sum(time_data['total']) / len(time_data['total'])
                    else:
                        avg_total = 0
                        
                    # Calculate average kernel time if available
                    if time_data['kernel']:
                        avg_kernel = sum(time_data['kernel']) / len(time_data['kernel'])
                    else:
                        avg_kernel = 0
                        
                    avg_times[t_str] = {
                        'total': avg_total,
                        'kernel': avg_kernel
                    }
                
                # Replace the times dictionary with the averages
                times = avg_times

                with open(out_path, 'rb') as outf:
                    data = outf.read()
                    
                logger.info(f"Successfully processed image, size: {len(data)} bytes")
                
                # Save processed image back to Minio with retries
                def put_minio_object(bucket, key, data, content_type='image/png', retries=5, delay=2):
                    """Put an object to MinIO with retries"""
                    last_error = None
                    for attempt in range(retries):
                        try:
                            minio_client.put_object(
                                bucket,
                                key,
                                io.BytesIO(data),
                                length=len(data),
                                content_type=content_type,
                            )
                            return True
                        except Exception as e:
                            last_error = e
                            logger.warning(f"Error uploading to MinIO (attempt {attempt+1}/{retries}): {e}")
                            time.sleep(delay)
                    raise last_error or RuntimeError("Failed to upload to MinIO")
                
                processed_key = f"processed/{os.path.basename(image_key)}"
                put_minio_object(BUCKET, processed_key, data, 'image/png')
                
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
            
            # Send error message back to frontend
            error_payload = {
                'image_key': image_key,
                'error': True,
                'error_message': str(e)
            }
            
            # Use delivery mode 2 for persistent messages
            properties = pika.BasicProperties(
                delivery_mode=2,  # make message persistent
            )
            
            try:
                channel.basic_publish(
                    exchange='',
                    routing_key='grayscale_processed',
                    body=json.dumps(error_payload).encode(),
                    properties=properties
                )
                logger.info(f"Published error message for {image_key}: {str(e)}")
            except Exception as publish_error:
                logger.error(f"Failed to publish error message: {publish_error}")
            
            raise
            
    except pika.exceptions.AMQPConnectionError as e:
        logger.error(f"RabbitMQ connection error: {e}")
        FAILURES.inc()
        
        # Try to reconnect
        if handle_rabbitmq_failure():
            logger.info("Successfully reconnected to RabbitMQ, but the current message was lost")
            # We'll nack the message to requeue it if possible
            try:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                logger.info("Message has been requeued for reprocessing")
            except Exception as nack_error:
                logger.error(f"Failed to requeue message: {nack_error}")
        else:
            logger.error("Failed to reconnect to RabbitMQ, rejecting message")
            try:
                ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
            except Exception:
                pass
                
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        FAILURES.inc()
        
        # Try to send an error message if possible
        try:
            if 'image_key' in locals():
                error_payload = {
                    'image_key': image_key,
                    'error': True,
                    'error_message': str(e)
                }
                
                # Ensure connection is still alive
                if not connection.is_open:
                    if handle_rabbitmq_failure():
                        # We got a new channel after reconnection
                        logger.info("Reconnected to RabbitMQ to send error message")
                
                properties = pika.BasicProperties(
                    delivery_mode=2,  # make message persistent
                )
                
                channel.basic_publish(
                    exchange='',
                    routing_key='grayscale_processed',
                    body=json.dumps(error_payload).encode(),
                    properties=properties
                )
                logger.info(f"Published error message for {image_key}: {str(e)}")
        except Exception:
            pass  # We tried our best to report the error
            
    finally:
        # Always acknowledge message to avoid getting stuck
        # Even if processing fails, we don't want to reprocess the same message
        ch.basic_ack(delivery_tag=method.delivery_tag)

# Add a function to recreate the RabbitMQ connection with exponential backoff
def create_rabbitmq_connection():
    """Create a new RabbitMQ connection with automatic reconnection"""
    global connection, channel
    
    try:
        # Close existing connection if it exists and is open - safely
        if 'connection' in globals():
            old_connection = connection
            # Set to None first to prevent heartbeat thread from using it
            connection = None
            
            if old_connection:
                try:
                    # Check if it has the is_open attribute before accessing
                    if hasattr(old_connection, 'is_open') and old_connection.is_open:
                        old_connection.close()
                        logger.info("Closed existing RabbitMQ connection")
                except Exception as e:
                    logger.warning(f"Error closing existing connection: {e}")
        
        # Create a new connection
        new_connection = connect_rabbitmq(rabbitmq_url, MAX_RECONNECT_ATTEMPTS, RECONNECT_DELAY)
        if not new_connection:
            logger.error("Failed to create new RabbitMQ connection")
            return False
            
        connection = new_connection
        channel = connection.channel()
        
        # Declare queues - make sure they're durable
        channel.queue_declare(queue='grayscale', durable=True)
        channel.queue_declare(queue='grayscale_processed', durable=True)
        
        # Set prefetch count to control how many messages we process at once
        channel.basic_qos(prefetch_count=PREFETCH_COUNT)
        
        logger.info("Successfully reconnected to RabbitMQ")
        return True
    except Exception as e:
        logger.error(f"Failed to reconnect to RabbitMQ: {e}")
        return False

def handle_rabbitmq_failure():
    """Handle RabbitMQ connection failure with exponential backoff"""
    global connection, channel
    
    # First check and set connection to None to avoid any thread using it
    if 'connection' in globals() and connection is not None:
        try:
            if hasattr(connection, 'is_open') and not connection.is_open:
                connection = None
                channel = None
        except Exception:
            connection = None
            channel = None
            
    max_retries = 10
    delay = 1  # Start with 1 second delay
    
    for i in range(max_retries):
        logger.warning(f"Attempting to reconnect to RabbitMQ (attempt {i+1}/{max_retries})")
        RECONNECT_ATTEMPTS.inc()
        
        # Add a try-except around the create_rabbitmq_connection call for extra safety
        try:
            if create_rabbitmq_connection():
                return True
        except Exception as e:
            logger.error(f"Error during reconnection attempt {i+1}: {e}")
            
        # Exponential backoff with jitter
        jitter = (delay * 0.2) * (2 * random.random() - 1)
        sleep_time = delay + jitter
        logger.warning(f"Waiting {sleep_time:.2f} seconds before next reconnection attempt")
        try:
            time.sleep(sleep_time)
        except Exception:
            # Just continue if sleep is interrupted
            pass
        delay = min(delay * 2, 30)  # Double the delay up to 30 seconds max
        
    logger.error("Failed to reconnect to RabbitMQ after multiple attempts")
    return False

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
