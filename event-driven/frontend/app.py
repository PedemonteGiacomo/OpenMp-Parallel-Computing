import io
import os
import uuid
import time
import threading

from flask import Flask, request, send_file, redirect, url_for, render_template_string
from minio import Minio
import pika
import json

BUCKET = 'images'

minio_client = Minio(
    os.environ.get('MINIO_ENDPOINT', 'minio:9000'),
    access_key=os.environ.get('MINIO_ACCESS_KEY', 'minioadmin'),
    secret_key=os.environ.get('MINIO_SECRET_KEY', 'minioadmin'),
    secure=False
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

# dictionary storing processed results indexed by original key
PROCESSED = {}

def consume_processed():
    """Background thread consuming completion messages."""
    proc_connection = connect_rabbitmq(os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/'))
    proc_channel = proc_connection.channel()
    proc_channel.queue_declare(queue='grayscale_processed')

    def cb(ch, method, properties, body):
        msg = json.loads(body)
        PROCESSED[msg['image_key']] = msg['processed_key']
        ch.basic_ack(delivery_tag=method.delivery_tag)

    proc_channel.basic_consume(queue='grayscale_processed', on_message_callback=cb)
    proc_channel.start_consuming()

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
    <button class='btn waves-effect waves-light' type='submit'>Upload</button>
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
  <script>
    async function poll() {
      const res = await fetch('/status?key={{ key }}');
      const data = await res.json();
      if (data.processed) {
        document.getElementById('processed-img').src = '/image/' + encodeURIComponent(data.processed_key);
        document.getElementById('processed-img').style.display = 'block';
        document.getElementById('status').textContent = 'Processed';
        clearInterval(timer);
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
        key = f"uploads/{uuid.uuid4().hex}_{file.filename}"
        minio_client.put_object(
            BUCKET,
            key,
            file.stream,
            length=-1,
            part_size=10 * 1024 * 1024,
            content_type=file.content_type,
        )
        channel.basic_publish('', 'grayscale', json.dumps({'image_key': key}).encode())
        return render_template_string(PAGE_TEMPLATE, key=key)
    return render_template_string(PAGE_TEMPLATE, key=None)

@app.route('/status')
def status():
    key = request.args['key']
    processed_key = PROCESSED.get(key)
    if not processed_key:
        return {'processed': False}
    return {'processed': True, 'processed_key': processed_key}

@app.route('/image/<path:key>')
def image(key):
    response = minio_client.get_object(BUCKET, key)
    return send_file(io.BytesIO(response.read()), mimetype='image/png')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
