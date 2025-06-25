import io
import os
import uuid
import time
import threading
import logging
from datetime import datetime
from flask import Flask, request, send_file, render_template_string
from minio import Minio
import pika
import json
from prometheus_client import Histogram, Counter, start_http_server, generate_latest, CONTENT_TYPE_LATEST
from functools import wraps

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BUCKET = 'images'

# Configure Minio client with retries
MAX_MINIO_RETRIES = 3
RETRY_BACKOFF = 2  # seconds

def with_retries(max_retries=3, backoff=1):
    """Decorator for function retries with exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    wait = backoff * (2 ** attempt)
                    logger.warning(f"Attempt {attempt+1}/{max_retries} failed: {e}. Retrying in {wait}s")
                    time.sleep(wait)
            # If we get here, all retries failed
            logger.error(f"All {max_retries} attempts failed. Last error: {last_exception}")
            raise last_exception
        return wrapper
    return decorator

@with_retries(MAX_MINIO_RETRIES, RETRY_BACKOFF)
def initialize_minio():
    minio_client = Minio(
        os.environ.get('MINIO_ENDPOINT', 'minio:9000'),
        access_key=os.environ.get('MINIO_ACCESS_KEY', 'minioadmin'),
        secret_key=os.environ.get('MINIO_SECRET_KEY', 'minioadmin'),
        secure=False
    )

    if not minio_client.bucket_exists(BUCKET):
        minio_client.make_bucket(BUCKET)
        
    return minio_client

minio_client = initialize_minio()

def connect_rabbitmq(url: str, retries: int = 10, delay: int = 5):
    for i in range(retries):
        try:
            params = pika.URLParameters(url)
            # Set heartbeat to detect broken connections faster
            params.heartbeat = 30
            # Set connection timeouts
            params.socket_timeout = 5
            # Add error callback
            return pika.BlockingConnection(params)
        except pika.exceptions.AMQPConnectionError:
            logger.warning(f"Waiting for RabbitMQ... ({i + 1}/{retries})")
            time.sleep(delay)
    raise RuntimeError("Could not connect to RabbitMQ")

# Connection and channel management
rabbitmq_lock = threading.Lock()
connection = None
channel = None

def get_rabbitmq_channel():
    """Get a RabbitMQ channel with reconnection logic"""
    global connection, channel
    
    with rabbitmq_lock:
        # Check if connection is closed or doesn't exist
        if connection is None or connection.is_closed:
            logger.info("Creating new RabbitMQ connection")
            connection = connect_rabbitmq(os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/'))
            channel = connection.channel()
            # Configure the channel with QoS to prevent overload
            channel.basic_qos(prefetch_count=10)
            # Declare queues - will be created if they don't exist
            channel.queue_declare(queue='grayscale', durable=True)
            channel.queue_declare(queue='grayscale_processed', durable=True)
        
        # Check if channel is closed
        elif channel is None or channel.is_closed:
            logger.info("Creating new RabbitMQ channel")
            channel = connection.channel()
            # Configure the channel with QoS
            channel.basic_qos(prefetch_count=10)
            # Declare queues - will be created if they don't exist
            channel.queue_declare(queue='grayscale', durable=True)
            channel.queue_declare(queue='grayscale_processed', durable=True)
        
        return channel

# Dictionary storing processed results indexed by original key
PROCESSED = {}
# Add a timestamp for cleaning up stale entries
PROCESSED_TIMESTAMPS = {}
# Lock to protect access to PROCESSED dict
processed_lock = threading.Lock()

# Add rate limiting
REQ_LIMIT = 10  # Per minute
REQ_TOKENS = REQ_LIMIT
REQ_LAST_CHECK = time.time()
REQ_LOCK = threading.Lock()

# Prometheus metrics
REQUEST_TIME = Histogram('frontend_request_seconds', 'Time from upload to result')
PUBLISH_COUNT = Counter('frontend_publish_total', 'Messages published to the queue')
PROCESSED_COUNT = Counter('frontend_processed_total', 'Messages processed notification received')
RABBITMQ_RECONNECTS = Counter('frontend_rabbitmq_reconnects', 'Number of RabbitMQ reconnections')
RABBITMQ_ERRORS = Counter('frontend_rabbitmq_errors', 'Number of RabbitMQ errors')
MINIO_ERRORS = Counter('frontend_minio_errors', 'Number of Minio errors')

# Expose metrics on port 8000
start_http_server(8000)

def cleanup_processed_entries():
    """Background thread to clean up old entries in the PROCESSED dict"""
    while True:
        try:
            now = time.time()
            # Keep entries for 1 hour max
            cutoff = now - 3600
            
            keys_to_remove = []
            with processed_lock:
                for key, timestamp in list(PROCESSED_TIMESTAMPS.items()):
                    if timestamp < cutoff:
                        keys_to_remove.append(key)
                
                # Remove old entries
                for key in keys_to_remove:
                    PROCESSED_TIMESTAMPS.pop(key, None)
                    PROCESSED.pop(key, None)
                
            if keys_to_remove:
                logger.info(f"Cleaned up {len(keys_to_remove)} old processed entries")
            
            # Check every 10 minutes
            time.sleep(600)
        except Exception as e:
            logger.error(f"Error in cleanup thread: {e}")
            time.sleep(60)

def consume_processed():
    """Background thread consuming completion messages."""
    while True:
        try:
            # Create a separate connection for the consumer
            proc_connection = connect_rabbitmq(os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/'))
            proc_channel = proc_connection.channel()
            proc_channel.queue_declare(queue='grayscale_processed', durable=True)

            def cb(ch, method, properties, body):
                try:
                    msg = json.loads(body)
                    image_key = msg['image_key']
                    with processed_lock:
                        info = PROCESSED.get(image_key, {})
                        info.update({
                            'processed_key': msg['processed_key'],
                            'times': msg.get('times', {}),
                            'passes': msg.get('passes'),
                        })
                        if 'start_ts' in info:
                            REQUEST_TIME.observe(time.time() - info['start_ts'])
                        PROCESSED[image_key] = info
                        # Update timestamp for cleanup
                        PROCESSED_TIMESTAMPS[image_key] = time.time()
                        
                    PROCESSED_COUNT.inc()
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Requeue the message if it's not a parsing error
                    if "JSONDecodeError" not in str(e):
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                    else:
                        # Bad message format, don't requeue
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

            # Set prefetch to limit message consumption rate
            proc_channel.basic_qos(prefetch_count=10)
            proc_channel.basic_consume(queue='grayscale_processed', on_message_callback=cb)
            
            logger.info("Starting to consume processed messages")
            proc_channel.start_consuming()
            
        except Exception as e:
            logger.error(f"Error in consumer thread: {e}")
            RABBITMQ_ERRORS.inc()
            # Sleep before reconnecting
            time.sleep(5)

# Start consumer threads
threading.Thread(target=consume_processed, daemon=True).start()
threading.Thread(target=cleanup_processed_entries, daemon=True).start()

app = Flask(__name__)

# Rate limiting middleware
def check_rate_limit():
    """Check and update rate limit tokens"""
    global REQ_TOKENS, REQ_LAST_CHECK
    
    with REQ_LOCK:
        now = time.time()
        # Add tokens for elapsed time (1 token per 60/REQ_LIMIT seconds)
        time_passed = now - REQ_LAST_CHECK
        new_tokens = time_passed * (REQ_LIMIT / 60.0)
        REQ_TOKENS = min(REQ_LIMIT, REQ_TOKENS + new_tokens)
        REQ_LAST_CHECK = now
        
        if REQ_TOKENS >= 1:
            REQ_TOKENS -= 1
            return True
        else:
            return False

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
    #error-message { color: red; display: none; }
    #loading { display: none; }
  </style>
</head>
<body class='container'>
  <h3>Grayscale Converter</h3>
  <form id="upload-form" method='post' enctype='multipart/form-data'>
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
      <input id='repeat' type='number' name='repeat' min='1' max='5' value='{{repeat_val}}'>
      <label for='repeat'>Runs per thread (max 5)</label>
    </div>
    <button class='btn waves-effect waves-light' id="submit-btn" type='submit'>Process</button>
    <div id="loading" class="progress">
      <div class="indeterminate"></div>
    </div>
    <div id="error-message"></div>
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
    // Initialize the charts with default configuration
    const timeChart = new Chart(document.getElementById('timeChart'), {
      type: 'bar',
      data: { 
        labels: [], 
        datasets: [{ 
          label: 'Time (s)', 
          data: [],
          backgroundColor: 'rgba(54, 162, 235, 0.7)',
          borderColor: 'rgba(54, 162, 235, 1)',
          borderWidth: 1
        }] 
      },
      options: { 
        responsive: true,
        maintainAspectRatio: false,
        animation: {
          duration: 500
        },
        scales: { 
          y: { 
            beginAtZero: true,
            title: {
              display: true,
              text: 'Time (seconds)'
            }
          },
          x: {
            title: {
              display: true,
              text: 'Number of Threads'
            }
          }
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
          },
          tooltip: {
            mode: 'index',
            intersect: false,
          }
        }
      }
    });
    
    const speedChart = new Chart(document.getElementById('speedChart'), {
      type: 'bar',
      data: { 
        labels: [], 
        datasets: [{ 
          label: 'Speed-up', 
          data: [],
          backgroundColor: 'rgba(75, 192, 192, 0.7)',
          borderColor: 'rgba(75, 192, 192, 1)',
          borderWidth: 1
        }] 
      },
      options: { 
        responsive: true,
        maintainAspectRatio: false,
        animation: {
          duration: 500
        },
        scales: { 
          y: { 
            beginAtZero: true,
            title: {
              display: true,
              text: 'Speed-up Factor'
            }
          },
          x: {
            title: {
              display: true,
              text: 'Number of Threads'
            }
          }
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
          },
          tooltip: {
            mode: 'index',
            intersect: false,
          }
        }
      }
    });
    
    let hasProcessed = false; // Flag to track if we've already processed data
    let pollAttempts = 0;
    const MAX_POLL_ATTEMPTS = 60; // 2 minutes with 2-second interval
    
    async function poll() {
      try {
        const res = await fetch('/status?key={{ key }}');
        if (!res.ok) {
          document.getElementById('status').textContent = `Error checking status: ${res.status}`;
          return;
        }
        
        const data = await res.json();
        
        if (data.processed && !hasProcessed) {
          // Only update the charts once when data is available
          hasProcessed = true;
          
          document.getElementById('processed-img').src = '/image/' + encodeURIComponent(data.processed_key);
          document.getElementById('processed-img').style.display = 'block';
          document.getElementById('status').textContent = 'Processing complete';
          
          // Get thread numbers in ascending order
          const threads = Object.keys(data.times)
            .map(t => parseInt(t))
            .sort((a, b) => a - b);
          
          // Get execution times for each thread count
          const times = threads.map(t => data.times[t]);
          
          // Calculate base time (single thread or lowest thread count)
          const base = times[0];
          
          // Calculate speedup for each thread count
          const speedups = times.map(time => base / time);
          
          // Update time chart
          timeChart.data.labels = threads.map(t => t.toString());
          timeChart.data.datasets[0].data = times;
          timeChart.update();
          
          // Update speedup chart
          speedChart.data.labels = threads.map(t => t.toString());
          speedChart.data.datasets[0].data = speedups;
          speedChart.update();
          
          // Stop polling since we've received and processed the data
          clearInterval(timer);
          
        } else if (!data.processed) {
          // Update status while waiting
          pollAttempts++;
          document.getElementById('status').textContent = `Processing... (polling ${pollAttempts}/${MAX_POLL_ATTEMPTS})`;
          
          // Stop polling after max attempts
          if (pollAttempts >= MAX_POLL_ATTEMPTS) {
            clearInterval(timer);
            document.getElementById('status').textContent = 'Processing timed out. The server may be overloaded.';
          }
        }
      } catch (err) {
        console.error("Error polling status:", err);
        document.getElementById('status').textContent = `Error polling: ${err.message}`;
      }
    }
    
    // Poll every 2 seconds
    const timer = setInterval(poll, 2000);
    
    // Initial poll
    poll();
    
    // Enhance form submission
    document.getElementById('upload-form').addEventListener('submit', function(e) {
      const fileInput = document.querySelector('input[name="image"]');
      const threadsInputs = document.querySelectorAll('input[name="threads"]:checked');
      
      if (!fileInput.files.length) {
        e.preventDefault();
        document.getElementById('error-message').textContent = 'Please select a file to upload';
        document.getElementById('error-message').style.display = 'block';
        return;
      }
      
      if (!threadsInputs.length) {
        e.preventDefault();
        document.getElementById('error-message').textContent = 'Please select at least one thread count';
        document.getElementById('error-message').style.display = 'block';
        return;
      }
      
      // Show loading indicator
      document.getElementById('submit-btn').disabled = true;
      document.getElementById('loading').style.display = 'block';
    });
  </script>
  {% endif %}
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Check rate limit
        if not check_rate_limit():
            return 'Too many requests. Please try again later.', 429
            
        try:
            file = request.files['image']
            if not file:
                return 'No file provided', 400
                
            threads = [int(t) for t in request.form.getlist('threads')] or [1]
            
            # Limit the number of thread tests and repeats to prevent overload
            threads = threads[:4]  # Max 4 thread counts
            
            try:
                repeat = min(int(request.form.get('repeat') or '1'), 5)  # Max 5 repeats
            except ValueError:
                repeat = 1
                
            key = f"uploads/{uuid.uuid4().hex}_{file.filename}"
            
            try:
                minio_client.put_object(
                    BUCKET,
                    key,
                    file.stream,
                    length=-1,
                    part_size=10 * 1024 * 1024,
                    content_type=file.content_type,
                )
            except Exception as e:
                logger.error(f"Minio error: {e}")
                MINIO_ERRORS.inc()
                return f"Error uploading file: {str(e)}", 500
                
            start_ts = time.time()
            msg = {
                'image_key': key,
                'threads': threads,
                'repeat': repeat,
                'sent_ts': start_ts
            }
            
            with processed_lock:
                PROCESSED[key] = {'start_ts': start_ts}
                PROCESSED_TIMESTAMPS[key] = start_ts
                
            try:
                # Get channel with reconnection logic
                ch = get_rabbitmq_channel()
                PUBLISH_COUNT.inc()
                ch.basic_publish(
                    '', 
                    'grayscale', 
                    json.dumps(msg).encode(), 
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Make message persistent
                        timestamp=int(time.time())
                    )
                )
            except Exception as e:
                logger.error(f"RabbitMQ publishing error: {e}")
                RABBITMQ_ERRORS.inc()
                return f"Error sending processing request: {str(e)}", 500
                
            return render_template_string(PAGE_TEMPLATE, key=key, threads_val=threads, repeat_val=repeat)
            
        except Exception as e:
            logger.error(f"Request processing error: {e}")
            return f"Error processing request: {str(e)}", 500
            
    return render_template_string(PAGE_TEMPLATE, key=None, threads_val=[1], repeat_val=1)

@app.route('/status')
def status():
    key = request.args.get('key')
    if not key:
        return {'error': 'No key provided'}, 400
        
    with processed_lock:
        info = PROCESSED.get(key)
        
    if not info:
        return {'processed': False, 'message': 'No record found for this key'}
        
    if 'processed_key' not in info:
        # Processing not completed yet
        return {'processed': False, 'message': 'Processing in progress'}
        
    resp = {'processed': True}
    resp.update(info)
    return resp

@app.route('/image/<path:key>')
def image(key):
    try:
        response = minio_client.get_object(BUCKET, key)
        return send_file(io.BytesIO(response.read()), mimetype='image/png')
    except Exception as e:
        logger.error(f"Error retrieving image {key}: {e}")
        MINIO_ERRORS.inc()
        return f"Error retrieving image: {str(e)}", 500

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

@app.route('/health')
def health():
    """Health check endpoint for monitoring"""
    status = {
        'status': 'up',
        'timestamp': datetime.utcnow().isoformat(),
        'rabbitmq_connected': False,
        'minio_connected': False
    }
    
    # Check RabbitMQ connection
    try:
        ch = get_rabbitmq_channel()
        status['rabbitmq_connected'] = not ch.is_closed
    except:
        status['rabbitmq_connected'] = False
        status['status'] = 'degraded'
    
    # Check Minio connection
    try:
        minio_client.list_buckets()
        status['minio_connected'] = True
    except:
        status['minio_connected'] = False
        status['status'] = 'degraded'
        
    http_status = 200 if status['status'] == 'up' else 500
    return status, http_status

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)
