import os
import time
import json
import logging
import threading
from typing import Dict, List
import pika
import docker
import requests
from prometheus_client import Gauge, Counter, start_http_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
RABBITMQ_URL = os.environ.get('RABBITMQ_URL', 'amqp://guest:guest@rabbitmq:5672/')
DOCKER_SOCKET = os.environ.get('DOCKER_SOCKET', '/var/run/docker.sock')
COMPOSE_PROJECT = os.environ.get('COMPOSE_PROJECT', 'event-driven')
SCALE_CHECK_INTERVAL = int(os.environ.get('SCALE_CHECK_INTERVAL', '30'))  # seconds
MAX_INSTANCES = int(os.environ.get('MAX_INSTANCES', '5'))
MIN_INSTANCES = int(os.environ.get('MIN_INSTANCES', '1'))

# Scaling thresholds
SCALE_UP_THRESHOLD = int(os.environ.get('SCALE_UP_THRESHOLD', '10'))  # messages per instance
SCALE_DOWN_THRESHOLD = int(os.environ.get('SCALE_DOWN_THRESHOLD', '2'))  # messages per instance

# Prometheus metrics
QUEUE_DEPTH = Gauge('scaler_queue_depth', 'Current queue depth', ['service'])
SERVICE_INSTANCES = Gauge('scaler_service_instances', 'Number of service instances', ['service'])
SCALING_EVENTS = Counter('scaler_scaling_events_total', 'Number of scaling events', ['service', 'action'])

class ServiceScaler:
    def __init__(self):
        self.docker_client = docker.from_env()
        self.rabbitmq_connection = None
        self.rabbitmq_channel = None
        self.services_config = {
            'grayscale_service': {
                'queue': 'image_processing',
                'compose_service': 'grayscale_service',
                'min_instances': MIN_INSTANCES,
                'max_instances': MAX_INSTANCES,
                'current_instances': 1,
                'last_scale_time': 0,
                'cooldown_period': 120,  # seconds before next scaling action
                'scaling_type': 'queue_based'
            },
            'api_gateway': {
                'compose_service': 'api_gateway',
                'min_instances': 1,
                'max_instances': 3,  # API Gateway doesn't need as many instances
                'current_instances': 1,
                'last_scale_time': 0,
                'cooldown_period': 180,  # longer cooldown for gateway
                'scaling_type': 'load_based',
                'health_endpoint': 'http://api_gateway:8000/api/v1/health',
                'load_threshold_up': 80,  # Scale up when >80% CPU or high response time
                'load_threshold_down': 30  # Scale down when <30% load
            }
        }
        # Don't fail startup if RabbitMQ is not ready yet
        self.connect_rabbitmq()
    
    def connect_rabbitmq(self):
        """Connect to RabbitMQ with proper heartbeat settings"""
        max_retries = 5
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Close existing connection if any
                if self.rabbitmq_connection and not self.rabbitmq_connection.is_closed:
                    self.rabbitmq_connection.close()
                
                # Configure connection parameters with heartbeat
                params = pika.URLParameters(RABBITMQ_URL)
                params.heartbeat = 600  # 10 minutes heartbeat (longer to avoid timeouts)
                params.socket_timeout = 5  # 5 seconds socket timeout
                params.blocked_connection_timeout = 300  # 5 minutes
                params.connection_attempts = 3
                params.retry_delay = 2
                
                self.rabbitmq_connection = pika.BlockingConnection(params)
                self.rabbitmq_channel = self.rabbitmq_connection.channel()
                logger.info("Connected to RabbitMQ successfully")
                return True
                
            except Exception as e:
                logger.warning(f"Failed to connect to RabbitMQ (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    logger.error("Failed to connect to RabbitMQ after all retries")
                    return False
    
    def ensure_rabbitmq_connection(self):
        """Ensure RabbitMQ connection is alive, reconnect if needed"""
        try:
            if not self.rabbitmq_connection or self.rabbitmq_connection.is_closed:
                return self.connect_rabbitmq()
            
            # Test the connection by processing events
            self.rabbitmq_connection.process_data_events(time_limit=0)
            return True
            
        except Exception as e:
            logger.warning(f"RabbitMQ connection lost: {e}")
            return self.connect_rabbitmq()
    
    def get_queue_depth(self, queue_name: str) -> int:
        """Get the current depth of a queue with retry logic"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # Ensure connection is alive
                if not self.ensure_rabbitmq_connection():
                    logger.error("Could not establish RabbitMQ connection")
                    return 0
                
                # Declare queue passively to get message count
                method = self.rabbitmq_channel.queue_declare(queue=queue_name, passive=True)
                message_count = method.method.message_count
                logger.debug(f"Queue {queue_name} has {message_count} messages")
                return message_count
                
            except pika.exceptions.ChannelClosedByBroker as e:
                logger.error(f"Queue {queue_name} not found: {e}")
                return 0
                
            except Exception as e:
                logger.warning(f"Failed to get queue depth for {queue_name} (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    # Force reconnection on next attempt
                    if self.rabbitmq_connection and not self.rabbitmq_connection.is_closed:
                        try:
                            self.rabbitmq_connection.close()
                        except:
                            pass
                    time.sleep(1)
                else:
                    logger.error(f"Failed to get queue depth for {queue_name} after all retries")
                    return 0
    
    def get_service_instances(self, service_name: str) -> int:
        """Get the current number of instances for a service"""
        try:
            containers = self.docker_client.containers.list(
                filters={'label': f'com.docker.compose.service={service_name}'}
            )
            return len([c for c in containers if c.status == 'running'])
        except Exception as e:
            logger.error(f"Failed to get service instances for {service_name}: {e}")
            return 1
    
    def scale_service(self, service_name: str, instances: int) -> bool:
        """Scale a service to the specified number of instances"""
        try:
            # Use docker compose to scale the service
            import subprocess
            
            cmd = [
                'docker', 'compose',
                '-p', 'event-driven',  # Use the same project name
                'up', '-d', '--scale', f'{service_name}={instances}'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd='/workspace')
            
            if result.returncode == 0:
                logger.info(f"Successfully scaled {service_name} to {instances} instances")
                return True
            else:
                logger.error(f"Failed to scale {service_name}: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error scaling service {service_name}: {e}")
            return False
    
    def calculate_desired_instances(self, service_config: dict, queue_depth: int) -> int:
        """Calculate the desired number of instances based on queue depth"""
        current_instances = service_config['current_instances']
        
        if queue_depth == 0:
            # No messages in queue, scale down to minimum
            return service_config['min_instances']
        
        # Calculate messages per instance
        messages_per_instance = queue_depth / current_instances if current_instances > 0 else queue_depth
        
        if messages_per_instance > SCALE_UP_THRESHOLD:
            # Scale up
            desired = min(current_instances + 1, service_config['max_instances'])
        elif messages_per_instance < SCALE_DOWN_THRESHOLD and current_instances > service_config['min_instances']:
            # Scale down
            desired = max(current_instances - 1, service_config['min_instances'])
        else:
            # No scaling needed
            desired = current_instances
        
        return desired
    
    def should_scale(self, service_config: dict) -> bool:
        """Check if enough time has passed since last scaling action"""
        return time.time() - service_config['last_scale_time'] > service_config['cooldown_period']
    
    def get_gateway_load_metrics(self, service_config: dict) -> dict:
        """Get load metrics for API Gateway instances"""
        try:
            health_endpoint = service_config.get('health_endpoint')
            if not health_endpoint:
                return {'cpu_usage': 0, 'response_time': 0, 'request_rate': 0}
            
            # Get health data from API Gateway
            response = requests.get(health_endpoint, timeout=5)
            health_data = response.json()
            
            # Calculate load metrics
            metrics = {
                'cpu_usage': 0,
                'response_time': response.elapsed.total_seconds() * 1000,  # ms
                'request_rate': 0,
                'queue_depths': []
            }
            
            # Extract queue depths as a load indicator
            if 'services' in health_data:
                for service_name, service_info in health_data['services'].items():
                    if 'queue_depth' in service_info:
                        metrics['queue_depths'].append(service_info['queue_depth'])
            
            # Calculate aggregate load score
            avg_queue_depth = sum(metrics['queue_depths']) / len(metrics['queue_depths']) if metrics['queue_depths'] else 0
            response_time_score = min(metrics['response_time'] / 100, 100)  # Normalize response time
            
            # Load score: combination of queue depth and response time
            metrics['load_score'] = min((avg_queue_depth * 10) + response_time_score, 100)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get gateway load metrics: {e}")
            return {'cpu_usage': 0, 'response_time': 0, 'request_rate': 0, 'load_score': 0}
    
    def calculate_gateway_desired_instances(self, service_config: dict, load_metrics: dict) -> int:
        """Calculate desired instances for API Gateway based on load"""
        current_instances = service_config['current_instances']
        load_score = load_metrics.get('load_score', 0)
        
        load_threshold_up = service_config.get('load_threshold_up', 80)
        load_threshold_down = service_config.get('load_threshold_down', 30)
        
        if load_score > load_threshold_up:
            # Scale up
            desired = min(current_instances + 1, service_config['max_instances'])
            logger.info(f"Gateway load high ({load_score:.1f}%), scaling up to {desired}")
        elif load_score < load_threshold_down and current_instances > service_config['min_instances']:
            # Scale down
            desired = max(current_instances - 1, service_config['min_instances'])
            logger.info(f"Gateway load low ({load_score:.1f}%), scaling down to {desired}")
        else:
            # No scaling needed
            desired = current_instances
        
        return desired

    def check_and_scale(self):
        """Check all services and scale if necessary"""
        logger.info("Checking services for scaling...")
        
        for service_name, service_config in self.services_config.items():
            try:
                current_instances = self.get_service_instances(service_config['compose_service'])
                
                # Update current instances in config
                service_config['current_instances'] = current_instances
                
                if service_config.get('scaling_type') == 'queue_based':
                    # Queue-based scaling for processing services
                    queue_depth = self.get_queue_depth(service_config['queue'])
                    
                    # Update metrics
                    QUEUE_DEPTH.labels(service=service_name).set(queue_depth)
                    SERVICE_INSTANCES.labels(service=service_name).set(current_instances)
                    
                    # Calculate desired instances based on queue depth
                    desired_instances = self.calculate_desired_instances(service_config, queue_depth)
                    
                    logger.info(f"{service_name}: Queue={queue_depth}, Current={current_instances}, Desired={desired_instances}")
                    
                elif service_config.get('scaling_type') == 'load_based':
                    # Load-based scaling for API Gateway
                    load_metrics = self.get_gateway_load_metrics(service_config)
                    
                    # Update metrics
                    SERVICE_INSTANCES.labels(service=service_name).set(current_instances)
                    
                    # Calculate desired instances based on load metrics
                    desired_instances = self.calculate_gateway_desired_instances(service_config, load_metrics)
                    
                    logger.info(f"{service_name}: Load={load_metrics.get('load_score', 0):.1f}%, Current={current_instances}, Desired={desired_instances}")
                else:
                    logger.warning(f"Unknown scaling type for {service_name}, skipping scaling")
                    continue
                
                # Check if scaling is needed and allowed
                if desired_instances != current_instances and self.should_scale(service_config):
                    logger.info(f"Scaling {service_name} from {current_instances} to {desired_instances} instances")
                    
                    if self.scale_service(service_config['compose_service'], desired_instances):
                        action = 'scale_up' if desired_instances > current_instances else 'scale_down'
                        SCALING_EVENTS.labels(service=service_name, action=action).inc()
                        service_config['last_scale_time'] = time.time()
                        service_config['current_instances'] = desired_instances
                        
                        logger.info(f"Successfully scaled {service_name} to {desired_instances} instances")
                    else:
                        logger.error(f"Failed to scale {service_name}")
                
            except Exception as e:
                logger.error(f"Error checking service {service_name}: {e}")
    
    def run(self):
        """Main scaling loop"""
        logger.info("Starting Service Scaler...")
        logger.info(f"Scale check interval: {SCALE_CHECK_INTERVAL} seconds")
        logger.info(f"Scale up threshold: {SCALE_UP_THRESHOLD} messages/instance")
        logger.info(f"Scale down threshold: {SCALE_DOWN_THRESHOLD} messages/instance")
        logger.info(f"Instance limits: {MIN_INSTANCES}-{MAX_INSTANCES}")
        
        try:
            while True:
                try:
                    self.check_and_scale()
                    time.sleep(SCALE_CHECK_INTERVAL)
                except KeyboardInterrupt:
                    logger.info("Shutting down Service Scaler...")
                    break
                except Exception as e:
                    logger.error(f"Error in scaling loop: {e}")
                    time.sleep(SCALE_CHECK_INTERVAL)
        finally:
            # Cleanup RabbitMQ connection
            if self.rabbitmq_connection and not self.rabbitmq_connection.is_closed:
                try:
                    self.rabbitmq_connection.close()
                    logger.info("Closed RabbitMQ connection")
                except Exception as e:
                    logger.warning(f"Error closing RabbitMQ connection: {e}")

class HealthMonitor:
    """Monitor service health and queue status"""
    
    def __init__(self, scaler: ServiceScaler):
        self.scaler = scaler
        
    def get_health_status(self) -> dict:
        """Get comprehensive health status"""
        status = {
            'timestamp': time.time(),
            'scaler_status': 'healthy',
            'services': {}
        }
        
        for service_name, service_config in self.scaler.services_config.items():
            if 'queue' in service_config:
                queue_depth = self.scaler.get_queue_depth(service_config['queue'])
            else:
                queue_depth = 0
            current_instances = self.scaler.get_service_instances(service_config['compose_service'])
            
            status['services'][service_name] = {
                'queue_depth': queue_depth,
                'current_instances': current_instances,
                'max_instances': service_config['max_instances'],
                'min_instances': service_config['min_instances'],
                'last_scale_time': service_config['last_scale_time'],
                'health_status': 'healthy' if current_instances > 0 else 'unhealthy'
            }
        
        return status

def create_health_api(scaler: ServiceScaler):
    """Create a simple health API"""
    from flask import Flask, jsonify
    
    app = Flask(__name__)
    health_monitor = HealthMonitor(scaler)
    
    @app.route('/health')
    def health():
        return jsonify(health_monitor.get_health_status())
    
    @app.route('/metrics')
    def metrics():
        # Prometheus metrics endpoint
        from prometheus_client import generate_latest
        return generate_latest()
    
    # Run Flask in a separate thread
    def run_api():
        app.run(host='0.0.0.0', port=8080, debug=False)
    
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    
    return app

if __name__ == '__main__':
    # Start Prometheus metrics server
    start_http_server(9090)
    logger.info("Started Prometheus metrics server on port 9090")
    
    # Create and start scaler
    scaler = ServiceScaler()
    
    # Start health API
    create_health_api(scaler)
    logger.info("Started health API on port 8080")
    
    # Run main scaling loop
    scaler.run()
