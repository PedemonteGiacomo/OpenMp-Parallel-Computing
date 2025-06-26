import io
import os
import uuid
import time
import threading
import logging
import random
from flask import Flask, request, send_file, render_template_string
from minio import Minio
import pika
import json
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BUCKET = 'images'

minio_client = Minio(
    os.environ.get('MINIO_ENDPOINT', 'minio:9000'),
    access_key=os.environ.get('MINIO_ACCESS_KEY', 'minioadmin'),
    secret_key=os.environ.get('MINIO_SECRET_KEY', 'minioadmin'),
    secure=False
)

# Make sure bucket exists
if not minio_client.bucket_exists(BUCKET):
    minio_client.make_bucket(BUCKET)
    logger.info(f"Created bucket: {BUCKET}")

# Setup a heartbeat thread to ensure we respond even when the main thread is busy
def start_heartbeat_thread(connection, interval=30):
    """Start a separate thread to process heartbeats and keep the connection alive"""
    def heartbeat_thread_func():
        while True:
            try:
                # Process heartbeats more frequently than the interval
                # This is important for ensuring RabbitMQ sees activity
                time.sleep(interval)
                # Process heartbeats if connection exists
                if connection and connection.is_open:
                    connection.process_data_events()
                    logger.debug("Heartbeat processed")
                else:
                    logger.warning("Connection closed, heartbeat thread exiting")
                    break
            except pika.exceptions.ConnectionClosed as e:
                logger.error(f"Connection closed in heartbeat thread: {e}")
                break
            except Exception as e:
                logger.error(f"Error in heartbeat thread: {e}")
                # Don't break - keep trying as long as the application runs
                time.sleep(5)
    
    thread = threading.Thread(target=heartbeat_thread_func, daemon=True)
    thread.start()
    logger.info("Started heartbeat thread")
    return thread

def connect_rabbitmq(url: str, retries: int = 10, delay: int = 5):
    for i in range(retries):
        try:
            params = pika.URLParameters(url)
            # Adjust timeout settings for better stability
            params.heartbeat = 30  # Reduced to 30 seconds for more frequent heartbeats
            params.socket_timeout = 300  # 5 minutes to be tolerant of network and processing delays
            params.blocked_connection_timeout = 300  # 5 minutes
            
            connection = pika.BlockingConnection(params)
            
            # Start heartbeat thread to ensure we process events even during Flask request handling
            start_heartbeat_thread(connection, interval=15)  # Process events every 15 seconds (half of heartbeat time)
            
            logger.info("Connected to RabbitMQ with heartbeat=%s seconds", params.heartbeat)
            return connection
        except pika.exceptions.AMQPConnectionError as e:
            logger.warning(f"Waiting for RabbitMQ... ({i + 1}/{retries}): {e}")
            time.sleep(delay)
    raise RuntimeError("Could not connect to RabbitMQ")

connection = connect_rabbitmq(os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/'))
channel = connection.channel()
channel.queue_declare(queue='grayscale', durable=True)
channel.queue_declare(queue='grayscale_processed', durable=True)

# dictionary storing processed results indexed by original key
PROCESSED = {}
# Lock to protect access to the PROCESSED dict
processed_lock = threading.Lock()

def consume_processed():
    """Background thread consuming completion messages."""
    reconnect_delay = 1  # Start with 1 second delay
    max_delay = 30       # Maximum delay between reconnection attempts
    
    while True:
        try:
            proc_connection = connect_rabbitmq(os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/'))
            proc_channel = proc_connection.channel()
            proc_channel.queue_declare(queue='grayscale_processed', durable=True)

            def cb(ch, method, properties, body):
                try:
                    msg = json.loads(body)
                    image_key = msg['image_key']
                    
                    # Check if this is an error message
                    if msg.get('error', False):
                        logger.error(f"Received error message for {image_key}: {msg.get('error_message', 'Unknown error')}")
                        with processed_lock:
                            PROCESSED[image_key] = {
                                'error': True,
                                'error_message': msg.get('error_message', 'An unknown error occurred during processing')
                            }
                    else:
                        # Normal success message
                        with processed_lock:
                            PROCESSED[image_key] = {
                                'processed_key': msg['processed_key'],
                                'times': msg.get('times', {}),
                                'passes': msg.get('passes'),
                            }
                        logger.info(f"Processed message for {image_key}")
                        
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except pika.exceptions.ConnectionClosed as e:
                    logger.error(f"Connection closed while processing message: {e}")
                    # Don't attempt to ack/nack as the connection is gone
                    # The reconnection logic in the outer loop will handle this
                    raise
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Requeue only if not a parsing error
                    if "JSONDecodeError" not in str(e):
                        try:
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        except pika.exceptions.ConnectionClosed:
                            # Connection already closed, nothing we can do
                            raise
                    else:
                        try:
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                        except pika.exceptions.ConnectionClosed:
                            # Connection already closed, nothing we can do
                            raise

            proc_channel.basic_qos(prefetch_count=1)
            proc_channel.basic_consume(queue='grayscale_processed', on_message_callback=cb)
            
            logger.info("Starting to consume processed messages")
            # Reset reconnect delay on successful connection
            reconnect_delay = 1
            proc_channel.start_consuming()
            
        except pika.exceptions.AMQPConnectionError as e:
            logger.error(f"AMQP connection error in consumer thread: {e}")
            # Use exponential backoff with jitter for reconnection
            jitter = (reconnect_delay * 0.2) * (2 * random.random() - 1)
            sleep_time = reconnect_delay + jitter
            logger.warning(f"Will attempt to reconnect in {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)
            reconnect_delay = min(reconnect_delay * 2, max_delay)
            
        except pika.exceptions.ConnectionClosed as e:
            logger.error(f"Connection closed in consumer thread: {e}")
            # Use exponential backoff with jitter for reconnection
            jitter = (reconnect_delay * 0.2) * (2 * random.random() - 1)
            sleep_time = reconnect_delay + jitter
            logger.warning(f"Will attempt to reconnect in {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)
            reconnect_delay = min(reconnect_delay * 2, max_delay)
            
        except Exception as e:
            logger.error(f"Error in consumer thread: {e}")
            # Use exponential backoff with jitter for reconnection
            jitter = (reconnect_delay * 0.2) * (2 * random.random() - 1)
            sleep_time = reconnect_delay + jitter
            logger.warning(f"Will attempt to reconnect in {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)
            reconnect_delay = min(reconnect_delay * 2, max_delay)

# start consumer thread
threading.Thread(target=consume_processed, daemon=True).start()

app = Flask(__name__)

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1'>
  <link href='https://cdnjs.cloudflare.com/ajax/libs/materialize/1.0.0/css/materialize.min.css' rel='stylesheet'>
  <script src='https://cdnjs.cloudflare.com/ajax/libs/materialize/1.0.0/js/materialize.min.js'></script>
  <script src='/static/chart.min.js'></script>
  <style>
    body { padding-top: 40px; }
    .card-image img { width: 100%; }
  </style>
</head>
<body class='container'>
  <h3>Grayscale Converter</h3>
  <form method='post' enctype='multipart/form-data'>
    <div class='file-field input-field'>
      <div class='btn'>
        <span>File</span>
        <input type='file' name='image'>
      </div>
      <div class='file-path-wrapper'>
        <input class='file-path validate' type='text'>
      </div>
    </div>
    <p>Threads to test:</p>
    {% for t in [1,2,4,6] %}
    <label>
      <input type='checkbox' name='threads' value='{{t}}' {% if t in threads_val %}checked{% endif %}>
      <span>{{t}}</span>
    </label>
    {% endfor %}
    <div class='input-field'>
      <input id='repeat' type='number' name='repeat' min='1' value='{{repeat_val}}'>
      <label for='repeat'>Runs per thread</label>
    </div>
    <div class='input-field'>
      <input id='passes' type='number' name='passes' min='1' value='{{passes_val}}'>
      <label for='passes'>Passes (complexity)</label>
    </div>
    <button class='btn waves-effect waves-light' type='submit'>Process</button>
  </form>
  
  {% if key %}
  <div class='row'>
    <div class='col s12 m6'>
      <div class='card z-depth-2'>
        <div class='card-image'>
          <img src='{{ url_for("image", key=key) }}'>
        </div>
        <div class='card-content'><span class='card-title'>Original</span></div>
      </div>
    </div>
    <div class='col s12 m6'>
      <div class='card z-depth-2'>
        <div class='card-image'>
          <img id='processed-img' style='display:none;'>
        </div>
        <div class='card-content'><span class='card-title' id='status'>Processing...</span></div>
      </div>
    </div>
  </div>
  <div class='row'>
    <div class='col s12 m6'>
      <canvas id='timeChart' height='150'></canvas>
    </div>
    <div class='col s12 m6'>
      <canvas id='speedChart' height='150'></canvas>
    </div>
  </div>
  <script>
    const timeChart = new Chart(document.getElementById('timeChart'), {
      type: 'bar',
      data: { labels: [], datasets: [{ label: 'Time (s)', data: [] }] },
      options: { scales: { y: { beginAtZero: true } } }
    });
    const speedChart = new Chart(document.getElementById('speedChart'), {
      type: 'bar',
      data: { labels: [], datasets: [{ label: 'Speed-up', data: [] }] },
      options: { scales: { y: { beginAtZero: true } } }
    });
    
    async function poll() {
      try {
        const res = await fetch('/status?key={{ key }}');
        const data = await res.json();
        if (data.processed) {
          // Check if there was an error during processing
          if (data.error) {
            document.getElementById('status').textContent = 'Error: ' + data.error_message;
            document.getElementById('status').style.color = 'red';
            clearInterval(timer);
            return;
          }
          
          // Normal successful processing
          document.getElementById('processed-img').src = '/image/' + encodeURIComponent(data.processed_key);
          document.getElementById('processed-img').style.display = 'block';
          document.getElementById('status').textContent = 'Done';
          const threads = Object.keys(data.times).map(t => parseInt(t)).sort((a,b)=>a-b);
          const times = threads.map(t => data.times[t]);
          threads.forEach((t,i) => {
            timeChart.data.labels.push(t.toString());
            timeChart.data.datasets[0].data.push(times[i]);
          });
          timeChart.update();
          const base = times[0];
          threads.forEach((t,i) => {
            speedChart.data.labels.push(t.toString());
            speedChart.data.datasets[0].data.push(base / times[i]);
          });
          speedChart.update();
          document.getElementById('status').textContent = 'Processed';
          clearInterval(timer);
        }
      } catch (err) {
        console.error('Error polling:', err);
      }
    }
    const timer = setInterval(poll, 2000);
    poll();
  </script>
  {% endif %}
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        file = request.files['image']
        if not file:
            return 'no file', 400
        threads = [int(t) for t in request.form.getlist('threads')] or [1]
        passes = request.form.get('passes') or '1'
        repeat = request.form.get('repeat') or '1'
        key = f"uploads/{uuid.uuid4().hex}_{file.filename}"
        minio_client.put_object(
            BUCKET,
            key,
            file.stream,
            length=-1,
            part_size=10 * 1024 * 1024,
            content_type=file.content_type,
        )
        msg = {
            'image_key': key,
            'threads': threads,
            'passes': int(passes),
            'repeat': int(repeat)
        }
        
        # Check connection status before publishing
        try:
            if not connection.is_open:
                logger.warning("RabbitMQ connection closed. Attempting to reconnect...")
                if not handle_rabbitmq_failure():
                    logger.error("Failed to reconnect to RabbitMQ")
                    return "Failed to connect to message queue. Please try again later.", 500
            
            channel.basic_publish('', 'grayscale', json.dumps(msg).encode())
            
        except pika.exceptions.AMQPConnectionError as e:
            logger.error(f"RabbitMQ connection error during publish: {e}")
            if not handle_rabbitmq_failure():
                logger.error("Failed to reconnect to RabbitMQ")
                return "Failed to connect to message queue. Please try again later.", 500
            # Try again after reconnection
            channel.basic_publish('', 'grayscale', json.dumps(msg).encode())
        return render_template_string(PAGE_TEMPLATE, key=key, threads_val=threads, passes_val=int(passes), repeat_val=int(repeat))
    return render_template_string(PAGE_TEMPLATE, key=None, threads_val=[1], passes_val=1, repeat_val=1)

@app.route('/status')
def status():
    key = request.args['key']
    with processed_lock:
        info = PROCESSED.get(key)
    if not info:
        return {'processed': False}
        
    resp = {'processed': True}
    resp.update(info)
    return resp

@app.route('/image/<path:key>')
def image(key):
    response = minio_client.get_object(BUCKET, key)
    return send_file(io.BytesIO(response.read()), mimetype='image/png')

def create_rabbitmq_connection():
    """Create a new RabbitMQ connection with automatic reconnection"""
    global connection, channel
    
    try:
        # Close existing connection if it exists and is open
        if 'connection' in globals() and connection and connection.is_open:
            try:
                connection.close()
                logger.info("Closed existing RabbitMQ connection")
            except Exception as e:
                logger.warning(f"Error closing existing connection: {e}")
        
        # Create a new connection
        connection = connect_rabbitmq(os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/'))
        channel = connection.channel()
        channel.queue_declare(queue='grayscale', durable=True)
        channel.queue_declare(queue='grayscale_processed', durable=True)
        logger.info("Successfully reconnected to RabbitMQ")
        return True
    except Exception as e:
        logger.error(f"Failed to reconnect to RabbitMQ: {e}")
        return False

def handle_rabbitmq_failure():
    """Handle RabbitMQ connection failure with exponential backoff"""
    max_retries = 10
    delay = 1  # Start with 1 second delay
    
    for i in range(max_retries):
        logger.warning(f"Attempting to reconnect to RabbitMQ (attempt {i+1}/{max_retries})")
        
        if create_rabbitmq_connection():
            return True
            
        # Exponential backoff with jitter
        jitter = (delay * 0.2) * (2 * random.random() - 1)
        sleep_time = delay + jitter
        logger.warning(f"Waiting {sleep_time:.2f} seconds before next reconnection attempt")
        time.sleep(sleep_time)
        delay = min(delay * 2, 30)  # Double the delay up to 30 seconds max
        
    logger.error("Failed to reconnect to RabbitMQ after multiple attempts")
    return False

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
