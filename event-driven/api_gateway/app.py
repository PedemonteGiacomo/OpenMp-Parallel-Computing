import os
import uuid
import time
import json
import logging
import threading
import io
from flask import Flask, request, jsonify, send_file
from minio import Minio
import pika
import requests
from prometheus_client import Counter, Histogram, start_http_server
import random

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
BUCKET = 'images'
MINIO_ENDPOINT = os.environ.get('MINIO_ENDPOINT', 'minio:9000')
MINIO_ACCESS_KEY = os.environ.get('MINIO_ACCESS_KEY', 'minioadmin')
MINIO_SECRET_KEY = os.environ.get('MINIO_SECRET_KEY', 'minioadmin')
RABBITMQ_URL = os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@rabbitmq:5672/')

# Service registry - in production this could be dynamic service discovery
SERVICES = {
    'grayscale': {
        'queue': 'image_processing',
        'endpoint': 'http://grayscale_service:8001',  # For health checks
        'description': 'Convert images to grayscale using OpenMP parallel processing'
    }
    # Future services can be added here:
    # 'sobel': {
    #     'queue': 'sobel_processing',
    #     'endpoint': 'http://sobel_service:8002',
    #     'description': 'Apply Sobel edge detection filter'
    # },
    # 'blur': {
    #     'queue': 'blur_processing', 
    #     'endpoint': 'http://blur_service:8003',
    #     'description': 'Apply Gaussian blur filter'
    # }
}

# Prometheus metrics
REQUEST_COUNT = Counter('api_gateway_requests_total', 'Total API requests', ['service', 'status'])
REQUEST_DURATION = Histogram('api_gateway_request_duration_seconds', 'Request duration', ['service'])
QUEUE_DEPTH = Histogram('api_gateway_queue_depth', 'Current queue depth', ['service'])

# Initialize MinIO client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

# Make sure bucket exists
if not minio_client.bucket_exists(BUCKET):
    minio_client.make_bucket(BUCKET)
    logger.info(f"Created bucket: {BUCKET}")

# In-memory status store (use Redis in production)
request_status = {}

# Completion message consumer
def start_completion_consumer():
    """Background thread to consume completion messages from services"""
    logger.info("CALLED start_completion_consumer function")
    def consumer_thread():
        logger.info("Starting completion message consumer...")
        while True:
            try:
                # Create a separate connection for consuming
                connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
                channel = connection.channel()
                
                # Declare the completion queue
                channel.queue_declare(queue='grayscale_processed', durable=True)
                
                def process_completion_message(ch, method, properties, body):
                    try:
                        data = json.loads(body)
                        request_id = data.get('image_key', '').replace('input/', '').replace('_input.png', '').replace('_input.jpg', '')
                        
                        if request_id and request_id in request_status:
                            # Update status with completion data
                            request_status[request_id].update({
                                'status': 'completed',
                                'completed_at': time.time(),
                                'processed_key': data.get('processed_key'),
                                'times': data.get('times', {}),
                                'passes': data.get('passes', 1),
                                'process_time': data.get('process_time', 0),
                                'download_url': f'/api/v1/download/{request_id}',
                                'image_url': f'/api/v1/image/{request_id}',
                                'result_url': f'/api/v1/result/{request_id}',
                                'original_image_url': f'/api/v1/image/{request_id}?type=input'
                            })
                            logger.info(f"Updated completion status for request {request_id} with performance data")
                        
                        # Acknowledge the message
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                        
                    except Exception as e:
                        logger.error(f"Error processing completion message: {e}")
                        # Acknowledge anyway to avoid redelivery
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                
                # Set up consumer
                channel.basic_consume(
                    queue='grayscale_processed',
                    on_message_callback=process_completion_message,
                    auto_ack=False
                )
                
                logger.info("Completion consumer started successfully")
                channel.start_consuming()
                
            except Exception as e:
                logger.error(f"Completion consumer error: {e}")
                time.sleep(5)  # Wait before retrying
    
    # Start the consumer thread
    consumer_thread_obj = threading.Thread(target=consumer_thread, daemon=True)
    consumer_thread_obj.start()
    return consumer_thread_obj

# RabbitMQ connection management
class RabbitMQManager:
    def __init__(self):
        self.connection = None
        self.channel = None
        self.connect()
    
    def connect(self):
        try:
            self.connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            self.channel = self.connection.channel()
            
            # Declare queues for all services
            for service_name, service_config in SERVICES.items():
                queue_name = service_config['queue']
                self.channel.queue_declare(queue=queue_name, durable=True)
                logger.info(f"Declared queue: {queue_name}")
                
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    def publish_message(self, queue_name, message):
        try:
            if not self.connection or self.connection.is_closed:
                self.connect()
                
            self.channel.basic_publish(
                exchange='',
                routing_key=queue_name,
                body=json.dumps(message),
                properties=pika.BasicProperties(delivery_mode=2)  # Make message persistent
            )
            logger.info(f"Published message to queue {queue_name}: {message['request_id']}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            return False
    
    def get_queue_depth(self, queue_name):
        try:
            if not self.connection or self.connection.is_closed:
                self.connect()
            method = self.channel.queue_declare(queue=queue_name, passive=True)
            return method.method.message_count
        except Exception as e:
            logger.error(f"Failed to get queue depth for {queue_name}: {e}")
            return 0

rabbitmq_manager = RabbitMQManager()

# API Routes

@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """Health check endpoint for the API Gateway"""
    status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'services': {}
    }
    
    # Check service availability
    for service_name, service_config in SERVICES.items():
        try:
            # Check if service endpoint is reachable
            response = requests.get(f"{service_config['endpoint']}/health", timeout=5)
            status['services'][service_name] = {
                'status': 'healthy' if response.status_code == 200 else 'unhealthy',
                'queue_depth': rabbitmq_manager.get_queue_depth(service_config['queue'])
            }
        except Exception as e:
            status['services'][service_name] = {
                'status': 'unhealthy',
                'error': str(e),
                'queue_depth': rabbitmq_manager.get_queue_depth(service_config['queue'])
            }
    
    return jsonify(status)

@app.route('/api/v1/services', methods=['GET'])
def list_services():
    """List available processing services"""
    services_info = {}
    for service_name, service_config in SERVICES.items():
        services_info[service_name] = {
            'description': service_config['description'],
            'queue_depth': rabbitmq_manager.get_queue_depth(service_config['queue']),
            'endpoint': f"/api/v1/process/{service_name}"
        }
    
    return jsonify({
        'services': services_info,
        'total_services': len(SERVICES)
    })

@app.route('/api/v1/process/<service_name>', methods=['POST'])
def process_image(service_name):
    """Process an image using the specified service"""
    start_time = time.time()
    
    # Validate service exists
    if service_name not in SERVICES:
        REQUEST_COUNT.labels(service=service_name, status='error').inc()
        return jsonify({
            'error': f'Service {service_name} not found',
            'available_services': list(SERVICES.keys())
        }), 404
    
    # Check if file was uploaded
    if 'image' not in request.files:
        REQUEST_COUNT.labels(service=service_name, status='error').inc()
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    if file.filename == '':
        REQUEST_COUNT.labels(service=service_name, status='error').inc()
        return jsonify({'error': 'No image file selected'}), 400
    
    try:
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        
        # Get processing parameters
        threads = request.form.get('threads', '4')
        runs = request.form.get('runs', '1')
        
        # Upload image to MinIO
        object_name = f"input/{request_id}_{file.filename}"
        file_data = file.read()
        file.seek(0)  # Reset file pointer
        
        minio_client.put_object(
            BUCKET,
            object_name,
            io.BytesIO(file_data),
            length=len(file_data),
            content_type=file.content_type or 'application/octet-stream'
        )
        
        logger.info(f"Uploaded {object_name} to MinIO")
        
        # Prepare message for the service
        message = {
            'request_id': request_id,
            'image_key': object_name,  # Changed from input_object to image_key
            'output_key': f'output/{request_id}_output.png',  # Changed from output_object to output_key
            'threads': threads,
            'runs': runs,
            'timestamp': time.time(),
            'service': service_name
        }
        
        # Send message to appropriate queue
        queue_name = SERVICES[service_name]['queue']
        success = rabbitmq_manager.publish_message(queue_name, message)
        
        if not success:
            REQUEST_COUNT.labels(service=service_name, status='error').inc()
            return jsonify({'error': 'Failed to queue processing request'}), 500

        # Store request status
        request_status[request_id] = {
            'request_id': request_id,
            'service': service_name,
            'status': 'queued',
            'submitted_at': time.time(),
            'parameters': {
                'threads': threads,
                'runs': runs
            },
            'input_object': object_name,
            'output_object': f'output/{request_id}_output.png'
        }
        
        # Record metrics
        REQUEST_COUNT.labels(service=service_name, status='success').inc()
        REQUEST_DURATION.labels(service=service_name).observe(time.time() - start_time)
        QUEUE_DEPTH.labels(service=service_name).observe(
            rabbitmq_manager.get_queue_depth(queue_name)
        )
        
        return jsonify({
            'request_id': request_id,
            'service': service_name,
            'status': 'queued',
            'message': f'Image processing request queued for {service_name} service',
            'poll_url': f'/api/v1/status/{request_id}',
            'parameters': {
                'threads': threads,
                'runs': runs
            }
        }), 202
        
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        REQUEST_COUNT.labels(service=service_name, status='error').inc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/status/<request_id>', methods=['GET'])
def get_status(request_id):
    """Get the status of a processing request"""
    try:
        # Check in-memory status store first
        if request_id in request_status:
            status_info = request_status[request_id].copy()
            
            # If status is still processing, check for completion via file existence
            if status_info['status'] in ['queued', 'processing']:
                output_object = status_info.get('output_object', f'output/{request_id}_output.png')
                
                try:
                    minio_client.stat_object(BUCKET, output_object)
                    # File exists - update status to completed, but preserve existing data
                    status_info['status'] = 'completed'
                    if 'completed_at' not in status_info:
                        status_info['completed_at'] = time.time()
                    if 'download_url' not in status_info:
                        status_info['download_url'] = f'/api/v1/download/{request_id}'
                    if 'image_url' not in status_info:
                        status_info['image_url'] = f'/api/v1/image/{request_id}'  # For viewing inline
                    if 'result_url' not in status_info:
                        status_info['result_url'] = f'/api/v1/result/{request_id}'
                    if 'original_image_url' not in status_info:
                        status_info['original_image_url'] = f'/api/v1/image/{request_id}?type=input'  # For viewing original
                    request_status[request_id] = status_info
                except Exception:
                    # Check for error file
                    error_object = f'errors/{request_id}_error.json'
                    try:
                        response = minio_client.get_object(BUCKET, error_object)
                        error_data = json.loads(response.read().decode())
                        status_info['status'] = 'failed'
                        status_info['error'] = error_data.get('error', 'Unknown error')
                        status_info['failed_at'] = time.time()
                        request_status[request_id] = status_info
                    except Exception:
                        # Still processing
                        status_info['status'] = 'processing'
            
            # Always include original image URL if we have input_object
            if 'input_object' in status_info:
                status_info['original_image_url'] = f'/api/v1/image/{request_id}?type=input'
            
            return jsonify(status_info)
        
        # Legacy check for requests not in memory (backward compatibility)
        output_object = f'output/{request_id}_output.png'
        
        try:
            minio_client.stat_object(BUCKET, output_object)
            return jsonify({
                'request_id': request_id,
                'status': 'completed',
                'download_url': f'/api/v1/download/{request_id}',
                'image_url': f'/api/v1/image/{request_id}',
                'result_url': f'/api/v1/result/{request_id}'
            })
        except Exception:
            pass
        
        # Check for error file
        error_object = f'errors/{request_id}_error.json'
        try:
            response = minio_client.get_object(BUCKET, error_object)
            error_data = json.loads(response.read().decode())
            return jsonify({
                'request_id': request_id,
                'status': 'failed',
                'error': error_data.get('error', 'Unknown error'),
                'details': error_data
            })
        except Exception:
            pass
        
        return jsonify({
            'request_id': request_id,
            'status': 'unknown',
            'message': 'Request not found'
        }), 404
        
    except Exception as e:
        logger.error(f"Error checking status for {request_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/download/<request_id>', methods=['GET'])
def download_result(request_id):
    """Download the processed image"""
    try:
        output_object = f'output/{request_id}_output.png'
        response = minio_client.get_object(BUCKET, output_object)
        
        return send_file(
            io.BytesIO(response.read()),
            mimetype='image/png',
            as_attachment=True,
            download_name=f'{request_id}_result.png'
        )
    except Exception as e:
        logger.error(f"Error downloading result for {request_id}: {e}")
        return jsonify({'error': 'Result not found or not ready'}), 404

@app.route('/api/v1/image/<request_id>', methods=['GET'])
def view_result_image(request_id):
    """View the processed or original image inline (for display in browser)"""
    try:
        # Check if requesting original image
        image_type = request.args.get('type', 'output')
        
        if image_type == 'input':
            # Try to find the original image (could be jpg or png)
            for ext in ['jpg', 'jpeg', 'png']:
                try:
                    input_object = f'input/{request_id}_input.{ext}'
                    response = minio_client.get_object(BUCKET, input_object)
                    mimetype = f'image/{ext}' if ext != 'jpg' else 'image/jpeg'
                    
                    return send_file(
                        io.BytesIO(response.read()),
                        mimetype=mimetype,
                        as_attachment=False,  # Display inline, not as download
                        download_name=f'{request_id}_original.{ext}'
                    )
                except Exception:
                    continue
            
            # If no original image found, return error
            return jsonify({'error': 'Original image not found'}), 404
        else:
            # Default: return processed image
            output_object = f'output/{request_id}_output.png'
            response = minio_client.get_object(BUCKET, output_object)
            
            return send_file(
                io.BytesIO(response.read()),
                mimetype='image/png',
                as_attachment=False,  # Display inline, not as download
                download_name=f'{request_id}_result.png'
            )
    except Exception as e:
        logger.error(f"Error viewing image for {request_id}: {e}")
        return jsonify({'error': 'Image not found or not ready'}), 404

@app.route('/api/v1/result/<request_id>', methods=['GET'])
def get_result_details(request_id):
    """Get detailed processing results including metrics"""
    try:
        # Try to get the metrics file
        metrics_object = f'metrics/{request_id}_metrics.json'
        try:
            response = minio_client.get_object(BUCKET, metrics_object)
            metrics_data = json.loads(response.read().decode())
            
            return jsonify({
                'request_id': request_id,
                'status': 'completed',
                'download_url': f'/api/v1/download/{request_id}',
                'metrics': metrics_data,
                'processing_details': {
                    'threads_used': metrics_data.get('threads'),
                    'processing_time': metrics_data.get('processing_time'),
                    'openmp_time': metrics_data.get('openmp_time'),
                    'efficiency': metrics_data.get('efficiency')
                }
            })
        except Exception:
            # Metrics file not available, return basic info
            return jsonify({
                'request_id': request_id,
                'status': 'completed',
                'download_url': f'/api/v1/download/{request_id}',
                'message': 'Processing completed but detailed metrics not available'
            })
            
    except Exception as e:
        logger.error(f"Error getting result details for {request_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/v1/queue/status', methods=['GET'])
def queue_status():
    """Get current queue status for all services"""
    status = {}
    for service_name, service_config in SERVICES.items():
        queue_name = service_config['queue']
        depth = rabbitmq_manager.get_queue_depth(queue_name)
        status[service_name] = {
            'queue_name': queue_name,
            'pending_messages': depth,
            'status': 'busy' if depth > 10 else 'available'
        }
    
    return jsonify({
        'queues': status,
        'timestamp': time.time()
    })

# Device-specific endpoints for adaptive frontend
@app.route('/api/v1/frontend/config', methods=['GET'])
def get_frontend_config():
    """Get frontend configuration based on device/connection type"""
    user_agent = request.headers.get('User-Agent', '').lower()
    
    # Simple device detection (in production, use more sophisticated detection)
    is_mobile = any(keyword in user_agent for keyword in ['mobile', 'android', 'iphone'])
    is_low_bandwidth = request.args.get('bandwidth') == 'low'
    
    config = {
        'ui_mode': 'mobile' if is_mobile else 'desktop',
        'max_concurrent_uploads': 1 if is_mobile else 3,
        'default_image_quality': 'low' if is_low_bandwidth else 'high',
        'polling_interval': 5000 if is_low_bandwidth else 2000,  # milliseconds
        'features': {
            'batch_processing': not is_mobile,
            'real_time_preview': not is_low_bandwidth,
            'advanced_metrics': not is_mobile
        },
        'services': list(SERVICES.keys())
    }
    
    return jsonify(config)

if __name__ == '__main__':
    # Start Prometheus metrics server
    start_http_server(8090)
    logger.info("Started Prometheus metrics server on port 8090")
    
    # Start completion message consumer
    logger.info("About to start completion consumer")
    try:
        start_completion_consumer()
        logger.info("Completion consumer started successfully")
    except Exception as e:
        logger.error(f"Failed to start completion consumer: {e}")
    
    # Start Flask app
    app.run(host='0.0.0.0', port=8000, debug=False)
