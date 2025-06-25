import io
import os
import uuid
import time
import threading
from flask import Flask, request, send_file, render_template_string
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
        PROCESSED[msg['image_key']] = {
            'processed_key': msg['processed_key'],
            'times': msg.get('times', {}),
            'passes': msg.get('passes'),
        }
PAGE_TEMPLATE = '''
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
    <div class='col s12 m6 chart-container'>
      <canvas id='timeChart'></canvas>
    </div>
    <div class='col s12 m6 chart-container'>
      <canvas id='speedChart'></canvas>
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true } }
      }
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true } }
      }
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
  <script>
    async function poll() {
      const res = await fetch('/status?key={{ key }}');
      const data = await res.json();
'''
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
        channel.basic_publish('', 'grayscale', json.dumps(msg).encode())
        return render_template_string(PAGE_TEMPLATE, key=key, threads_val=threads, passes_val=passes, repeat_val=repeat)
    return render_template_string(PAGE_TEMPLATE, key=None, threads_val=[1], passes_val=1, repeat_val=1)
        channel.basic_publish('', 'grayscale', json.dumps({'image_key': key}).encode())
        return render_template_string(PAGE_TEMPLATE, key=key)
    return render_template_string(PAGE_TEMPLATE, key=None)

@app.route('/status')
def status():
    key = request.args['key']
    info = PROCESSED.get(key)
    if not info:
        return {'processed': False}
    resp = {'processed': True}
    resp.update(info)
    return resp
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
