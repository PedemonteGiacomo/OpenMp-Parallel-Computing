#!/usr/bin/env python3

import os
import time
import logging
import docker
import tempfile
import shutil
from typing import List

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NginxConfigManager:
    """Manages Nginx configuration for dynamic API Gateway scaling"""
    
    def __init__(self):
        self.docker_client = docker.from_env()
        self.config_template_path = '/app/nginx.conf.template'
        self.config_path = '/etc/nginx/nginx.conf'
        self.nginx_container_name = 'nginx_lb'
        
    def get_api_gateway_instances(self) -> List[str]:
        """Get list of running API Gateway instances"""
        try:
            containers = self.docker_client.containers.list(
                filters={'label': 'com.docker.compose.service=api_gateway'}
            )
            
            instances = []
            for container in containers:
                if container.status == 'running':
                    # Get container IP and port
                    networks = container.attrs['NetworkSettings']['Networks']
                    for network_name, network_info in networks.items():
                        if 'event-driven' in network_name:  # Adjust for your compose project name
                            ip = network_info['IPAddress']
                            instances.append(f"{container.name}:8000")
                            break
            
            return instances
        except Exception as e:
            logger.error(f"Failed to get API Gateway instances: {e}")
            return []
    
    def generate_nginx_config(self, instances: List[str]) -> str:
        """Generate Nginx configuration with current instances"""
        
        # Base template
        upstream_servers = ""
        for instance in instances:
            upstream_servers += f"        server {instance} max_fails=3 fail_timeout=30s;\n"
        
        if not upstream_servers:
            # Fallback to primary instance
            upstream_servers = "        server api_gateway:8000 max_fails=3 fail_timeout=30s;\n"
        
        config = f"""events {{
    worker_connections 1024;
}}

http {{
    # Upstream configuration for API Gateway instances
    upstream api_gateway_backend {{
        # Health check enabled
        least_conn;
        
        # Dynamic API Gateway instances
{upstream_servers}
    }}
    
    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    
    # Connection limiting
    limit_conn_zone $binary_remote_addr zone=conn_limit:10m;
    
    # Log format
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time uct="$upstream_connect_time" '
                    'uht="$upstream_header_time" urt="$upstream_response_time"';
    
    access_log /var/log/nginx/access.log main;
    error_log /var/log/nginx/error.log warn;
    
    # Main server configuration
    server {{
        listen 80;
        server_name _;
        
        # Security headers
        add_header X-Frame-Options DENY;
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";
        
        # Rate limiting
        limit_req zone=api_limit burst=20 nodelay;
        limit_conn conn_limit 20;
        
        # Client request size limit
        client_max_body_size 50M;
        
        # Timeouts
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Health check endpoint for the load balancer itself
        location /nginx/health {{
            access_log off;
            return 200 "healthy\\n";
            add_header Content-Type text/plain;
        }}
        
        # Metrics endpoint for monitoring
        location /nginx/metrics {{
            access_log off;
            stub_status on;
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            allow 172.16.0.0/12;
            allow 192.168.0.0/16;
            deny all;
        }}
        
        # Proxy all other requests to API Gateway backend
        location / {{
            proxy_pass http://api_gateway_backend;
            
            # Headers for backend
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Load balancing headers
            proxy_set_header X-Load-Balancer nginx;
            proxy_set_header X-Upstream-Server $upstream_addr;
            
            # Keep alive connections
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            
            # Handle websockets if needed
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            
            # Buffer settings
            proxy_buffering on;
            proxy_buffer_size 128k;
            proxy_buffers 4 256k;
            proxy_busy_buffers_size 256k;
            
            # Retry logic
            proxy_next_upstream error timeout invalid_header http_500 http_502 http_503 http_504;
            proxy_next_upstream_tries 3;
            proxy_next_upstream_timeout 10s;
        }}
    }}
}}"""
        
        return config
    
    def update_nginx_config(self, instances: List[str]) -> bool:
        """Update Nginx configuration and reload"""
        try:
            # Generate new configuration
            new_config = self.generate_nginx_config(instances)
            
            # Write to temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.conf') as temp_file:
                temp_file.write(new_config)
                temp_file_path = temp_file.name
            
            # Get Nginx container
            nginx_container = self.docker_client.containers.get(self.nginx_container_name)
            
            # Copy new config to container
            with open(temp_file_path, 'rb') as temp_file:
                nginx_container.put_archive('/etc/nginx/', temp_file.read())
            
            # Test configuration
            result = nginx_container.exec_run('nginx -t')
            if result.exit_code != 0:
                logger.error(f"Nginx configuration test failed: {result.output.decode()}")
                return False
            
            # Reload Nginx
            result = nginx_container.exec_run('nginx -s reload')
            if result.exit_code == 0:
                logger.info(f"Nginx configuration updated with {len(instances)} API Gateway instances")
                return True
            else:
                logger.error(f"Failed to reload Nginx: {result.output.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to update Nginx configuration: {e}")
            return False
        finally:
            # Clean up temporary file
            if 'temp_file_path' in locals():
                os.unlink(temp_file_path)
    
    def monitor_and_update(self, check_interval: int = 30):
        """Monitor API Gateway instances and update Nginx configuration"""
        logger.info("Starting Nginx configuration monitor...")
        last_instances = []
        
        while True:
            try:
                current_instances = self.get_api_gateway_instances()
                
                # Check if instances have changed
                if set(current_instances) != set(last_instances):
                    logger.info(f"API Gateway instances changed: {current_instances}")
                    
                    if self.update_nginx_config(current_instances):
                        last_instances = current_instances
                    else:
                        logger.error("Failed to update Nginx configuration")
                
                time.sleep(check_interval)
                
            except KeyboardInterrupt:
                logger.info("Stopping Nginx configuration monitor...")
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                time.sleep(check_interval)

if __name__ == '__main__':
    manager = NginxConfigManager()
    manager.monitor_and_update()
