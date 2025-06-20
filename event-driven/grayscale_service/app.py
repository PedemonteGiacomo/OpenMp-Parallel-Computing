import io
import json
import os

from PIL import Image
from minio import Minio
import pika

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
channel.queue_declare(queue='grayscale_processed')


def process(ch, method, properties, body):
    msg = json.loads(body)
    image_key = msg['image_key']
    resp = minio_client.get_object(BUCKET, image_key)
    img = Image.open(resp)
    gray = img.convert('L')
    buf = io.BytesIO()
    gray.save(buf, format='PNG')
    buf.seek(0)
    processed_key = f"processed/{os.path.basename(image_key)}"
    minio_client.put_object(BUCKET, processed_key, buf, length=len(buf.getvalue()), content_type='image/png')
    channel.basic_publish(
        '',
        'grayscale_processed',
        json.dumps({'image_key': image_key, 'processed_key': processed_key}).encode()
    )
    ch.basic_ack(delivery_tag=method.delivery_tag)


channel.basic_consume(queue='grayscale', on_message_callback=process)
print(' [*] Waiting for messages. To exit press CTRL+C')
channel.start_consuming()
