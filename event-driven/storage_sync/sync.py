#!/usr/bin/env python3

import os
import time
import logging
import hashlib
from typing import Dict, List, Set
from datetime import datetime
from minio import Minio
from minio.error import S3Error
from prometheus_client import Counter, Histogram, start_http_server
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Prometheus metrics
SYNC_OPERATIONS = Counter('storage_sync_operations_total', 'Total sync operations', ['source', 'destination', 'status'])
SYNC_DURATION = Histogram('storage_sync_duration_seconds', 'Time spent on sync operations', ['operation'])
FILES_SYNCED = Counter('storage_sync_files_total', 'Total files synchronized', ['direction'])

class DistributedStorageSync:
    """Handles synchronization between distributed MinIO instances"""
    
    def __init__(self):
        self.bucket_name = 'images'
        self.sync_interval = int(os.environ.get('SYNC_INTERVAL', '60'))
        
        # Initialize MinIO clients
        self.global_client = self._create_client(
            os.environ.get('GLOBAL_MINIO_ENDPOINT', 'minio_global:9000')
        )
        
        self.service_clients = {
            'service1': self._create_client(
                os.environ.get('SERVICE1_MINIO_ENDPOINT', 'minio_service1:9000')
            ),
            'service2': self._create_client(
                os.environ.get('SERVICE2_MINIO_ENDPOINT', 'minio_service2:9000')
            )
        }
        
        # Ensure buckets exist
        self._ensure_buckets()
        
        # File tracking
        self.last_sync_times = {}
        self.known_files = {}
    
    def _create_client(self, endpoint: str) -> Minio:
        """Create MinIO client"""
        return Minio(
            endpoint,
            access_key=os.environ.get('MINIO_ACCESS_KEY', 'minioadmin'),
            secret_key=os.environ.get('MINIO_SECRET_KEY', 'minioadmin'),
            secure=False
        )
    
    def _ensure_buckets(self):
        """Ensure bucket exists in all MinIO instances"""
        clients = {'global': self.global_client, **self.service_clients}
        
        for name, client in clients.items():
            try:
                if not client.bucket_exists(self.bucket_name):
                    client.make_bucket(self.bucket_name)
                    logger.info(f"Created bucket '{self.bucket_name}' in {name}")
            except Exception as e:
                logger.error(f"Failed to ensure bucket in {name}: {e}")
    
    def _get_file_info(self, client: Minio, object_name: str) -> Dict:
        """Get file information including hash"""
        try:
            stat = client.stat_object(self.bucket_name, object_name)
            
            # Get file content to calculate hash
            response = client.get_object(self.bucket_name, object_name)
            content = response.read()
            response.close()
            
            file_hash = hashlib.md5(content).hexdigest()
            
            return {
                'name': object_name,
                'size': stat.size,
                'last_modified': stat.last_modified,
                'hash': file_hash,
                'content': content
            }
        except Exception as e:
            logger.error(f"Failed to get file info for {object_name}: {e}")
            return None
    
    def _list_objects(self, client: Minio) -> Set[str]:
        """List all objects in bucket"""
        try:
            objects = client.list_objects(self.bucket_name, recursive=True)
            return {obj.object_name for obj in objects}
        except Exception as e:
            logger.error(f"Failed to list objects: {e}")
            return set()
    
    def _copy_file(self, src_client: Minio, dst_client: Minio, object_name: str, src_name: str, dst_name: str) -> bool:
        """Copy file between MinIO instances"""
        try:
            with SYNC_DURATION.labels(operation='copy_file').time():
                # Get file from source
                file_info = self._get_file_info(src_client, object_name)
                if not file_info:
                    return False
                
                # Upload to destination
                from io import BytesIO
                dst_client.put_object(
                    self.bucket_name,
                    object_name,
                    BytesIO(file_info['content']),
                    length=len(file_info['content'])
                )
                
                logger.info(f"Copied {object_name} from {src_name} to {dst_name}")
                FILES_SYNCED.labels(direction=f"{src_name}_to_{dst_name}").inc()
                SYNC_OPERATIONS.labels(source=src_name, destination=dst_name, status='success').inc()
                return True
                
        except Exception as e:
            logger.error(f"Failed to copy {object_name} from {src_name} to {dst_name}: {e}")
            SYNC_OPERATIONS.labels(source=src_name, destination=dst_name, status='error').inc()
            return False
    
    def _sync_to_global(self):
        """Sync files from service instances to global instance"""
        logger.info("Syncing service instances to global storage...")
        
        global_files = self._list_objects(self.global_client)
        
        for service_name, service_client in self.service_clients.items():
            try:
                service_files = self._list_objects(service_client)
                
                # Find files that exist in service but not in global
                new_files = service_files - global_files
                
                for file_name in new_files:
                    if self._copy_file(service_client, self.global_client, file_name, service_name, 'global'):
                        global_files.add(file_name)
                
                if new_files:
                    logger.info(f"Synced {len(new_files)} files from {service_name} to global")
                    
            except Exception as e:
                logger.error(f"Error syncing {service_name} to global: {e}")
    
    def _sync_from_global(self):
        """Sync files from global instance to service instances"""
        logger.info("Syncing global storage to service instances...")
        
        global_files = self._list_objects(self.global_client)
        
        for service_name, service_client in self.service_clients.items():
            try:
                service_files = self._list_objects(service_client)
                
                # Find files that exist in global but not in service
                missing_files = global_files - service_files
                
                for file_name in missing_files:
                    # Only sync input files and results relevant to this service
                    if self._should_sync_to_service(file_name, service_name):
                        self._copy_file(self.global_client, service_client, file_name, 'global', service_name)
                
                if missing_files:
                    synced_count = len([f for f in missing_files if self._should_sync_to_service(f, service_name)])
                    if synced_count > 0:
                        logger.info(f"Synced {synced_count} files from global to {service_name}")
                    
            except Exception as e:
                logger.error(f"Error syncing global to {service_name}: {e}")
    
    def _should_sync_to_service(self, file_name: str, service_name: str) -> bool:
        """Determine if a file should be synced to a specific service"""
        # Sync input files to all services
        if file_name.startswith('input/'):
            return True
        
        # Sync output files only if they were processed by this service
        # This is a simple heuristic - in practice, you'd have metadata
        if file_name.startswith('output/'):
            # For now, sync all output files for simplicity
            return True
        
        # Sync error files
        if file_name.startswith('errors/'):
            return True
        
        # Don't sync metrics files (service-specific)
        if file_name.startswith('metrics/'):
            return False
        
        return True
    
    def _cross_service_sync(self):
        """Sync files between service instances"""
        logger.info("Cross-syncing between service instances...")
        
        service_names = list(self.service_clients.keys())
        
        for i, src_service in enumerate(service_names):
            for dst_service in service_names[i+1:]:
                try:
                    src_client = self.service_clients[src_service]
                    dst_client = self.service_clients[dst_service]
                    
                    src_files = self._list_objects(src_client)
                    dst_files = self._list_objects(dst_client)
                    
                    # Sync input files bidirectionally
                    src_inputs = {f for f in src_files if f.startswith('input/')}
                    dst_inputs = {f for f in dst_files if f.startswith('input/')}
                    
                    # Sync missing input files
                    for file_name in src_inputs - dst_inputs:
                        self._copy_file(src_client, dst_client, file_name, src_service, dst_service)
                    
                    for file_name in dst_inputs - src_inputs:
                        self._copy_file(dst_client, src_client, file_name, dst_service, src_service)
                        
                except Exception as e:
                    logger.error(f"Error cross-syncing {src_service} and {dst_service}: {e}")
    
    def sync_cycle(self):
        """Perform one complete sync cycle"""
        logger.info("Starting sync cycle...")
        start_time = time.time()
        
        try:
            # 1. Sync from services to global (results upload)
            self._sync_to_global()
            
            # 2. Sync from global to services (shared inputs)
            self._sync_from_global()
            
            # 3. Cross-sync between services (input sharing)
            self._cross_service_sync()
            
            duration = time.time() - start_time
            logger.info(f"Sync cycle completed in {duration:.2f} seconds")
            
        except Exception as e:
            logger.error(f"Error in sync cycle: {e}")
    
    def run(self):
        """Main sync loop"""
        logger.info("Starting Distributed Storage Sync...")
        logger.info(f"Sync interval: {self.sync_interval} seconds")
        logger.info(f"Global endpoint: {os.environ.get('GLOBAL_MINIO_ENDPOINT')}")
        logger.info(f"Service endpoints: {list(self.service_clients.keys())}")
        
        while True:
            try:
                self.sync_cycle()
                time.sleep(self.sync_interval)
            except KeyboardInterrupt:
                logger.info("Shutting down Storage Sync...")
                break
            except Exception as e:
                logger.error(f"Error in main sync loop: {e}")
                time.sleep(self.sync_interval)

def create_health_api(syncer):
    """Create health API for storage sync"""
    from flask import Flask, jsonify
    
    app = Flask(__name__)
    
    @app.route('/health')
    def health():
        return jsonify({
            'status': 'healthy',
            'sync_interval': syncer.sync_interval,
            'endpoints': {
                'global': os.environ.get('GLOBAL_MINIO_ENDPOINT'),
                'services': list(syncer.service_clients.keys())
            },
            'timestamp': time.time()
        })
    
    @app.route('/metrics')
    def metrics():
        from prometheus_client import generate_latest
        return generate_latest()
    
    def run_api():
        app.run(host='0.0.0.0', port=8080, debug=False)
    
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    
    return app

if __name__ == '__main__':
    # Start Prometheus metrics server
    start_http_server(9090)
    logger.info("Started Prometheus metrics server on port 9090")
    
    # Create syncer
    syncer = DistributedStorageSync()
    
    # Start health API
    create_health_api(syncer)
    logger.info("Started health API on port 8080")
    
    # Run sync loop
    syncer.run()
