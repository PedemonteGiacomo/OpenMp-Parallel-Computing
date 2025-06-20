import io
import os
import uuid

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

connection = pika.BlockingConnection(pika.URLParameters(os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@localhost:5672/')))
channel = connection.channel()
channel.queue_declare(queue='grayscale')

app = Flask(__name__)

UPLOAD_FORM = """
<h1>Upload image for grayscale processing</h1>
<form method='post' enctype='multipart/form-data'>
  <input type='file' name='image'>
  <input type='submit' value='Upload'>
</form>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        file = request.files['image']
        if not file:
            return 'no file', 400
        key = f"uploads/{uuid.uuid4().hex}_{file.filename}"
        minio_client.put_object(BUCKET, key, file.stream, length=-1, part_size=10*1024*1024, content_type=file.content_type)
        channel.basic_publish('', 'grayscale', json.dumps({'image_key': key}).encode())
        return redirect(url_for('check', key=key))
    return render_template_string(UPLOAD_FORM)

@app.route('/check')
def check():
    key = request.args['key']
    processed_key = f"processed/{os.path.basename(key)}"
    try:
        response = minio_client.get_object(BUCKET, processed_key)
    except Exception:
        return '<p>Still processing...</p>'
    return send_file(io.BytesIO(response.read()), mimetype='image/png')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
