# Scalable API Gateway Architecture Documentation

## Overview

This enhanced event-driven architecture introduces a **Scalable API Gateway** that serves as a load-balanced entry point for all processing requests. The architecture provides:

1. **Service Abstraction**: Frontend applications interact with a unified API instead of directly connecting to individual microservices
2. **Device Adaptation**: Different frontend experiences based on device type and connection quality
3. **Auto-scaling**: Automatic scaling of both API Gateway and processing services based on load
4. **Service Discovery**: Dynamic registration and discovery of processing services
5. **Load Balancing**: Nginx-based load balancing for API Gateway instances
6. **Storage Options**: Centralized or distributed storage architectures

## Architecture Components

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Frontend      │    │ Nginx Load Bal.  │    │ Service Scaler  │
│  (Adaptive)     │────│ (Gateway LB)     │    │ (Auto-scale)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                         │
                                │                         │
                       ┌────────▼──────────┐             │
                       │  API Gateway      │◄────────────┘
                       │  (1-3 instances)  │
                       └────────┬──────────┘
                                │
                       ┌────────▼──────────┐
                       │     RabbitMQ      │
                       │   (Message Bus)   │
                       └────────┬──────────┘
                                │
                    ┌───────────▼────────────┐
                    │  Processing Services   │
                    │  • grayscale_service   │
                    │  • (1-5 instances ea.) │
                    └────────────────────────┘
                                │
                       ┌────────▼──────────┐
                       │      Storage      │
                       │ (Centralized or   │
                       │   Distributed)    │
                       └───────────────────┘
```

## Key Features

### 1. Load Balancer (`nginx_lb` service)
- **Port**: 8000 (Entry point for all traffic)
- **Purpose**: Load balance traffic across multiple API Gateway instances
- **Features**:
  - Nginx-based load balancing with least connections algorithm
  - Health checks for upstream API Gateway instances
  - Rate limiting and connection limiting
  - Automatic failover and retry logic
  - SSL termination ready

### 2. API Gateway (`api_gateway` service - Scalable)
- **Port**: 8000 (Internal), 8090 (Metrics)
- **Instances**: 1-3 (auto-scaled based on load)
- **Purpose**: Service orchestration and request routing
- **Scaling Triggers**:
  - Load score > 80%: Scale up
  - Load score < 30%: Scale down
  - Response time > 100ms: Contributes to scale up
  - Queue depths: Monitored for load calculation

### 3. Adaptive Frontend (`frontend_gateway` service)
- **Port**: 8080
- **Purpose**: Device-aware frontend that adapts to mobile/desktop and bandwidth
- **Features**:
  - Mobile-optimized UI for small screens
  - Bandwidth-aware settings
  - Real-time processing status
  - Progressive enhancement

### 4. Service Scaler (`service_scaler` service)
- **Port**: 8082 (Health API), 9090 (Metrics)
- **Purpose**: Automatically scales processing services based on demand
- **Features**:
  - Queue depth monitoring
  - Automatic scaling up/down
  - Configurable thresholds
  - Cooldown periods to prevent oscillation

## Service Endpoints

### API Gateway Endpoints

| Endpoint | Method | Description |
|----------|---------|-------------|
| `/api/v1/health` | GET | System health status |
| `/api/v1/services` | GET | Available processing services |
| `/api/v1/process/{service}` | POST | Submit processing request |
| `/api/v1/status/{request_id}` | GET | Get processing status |
| `/api/v1/download/{request_id}` | GET | Download processed result |
| `/api/v1/result/{request_id}` | GET | Get detailed processing metrics |
| `/api/v1/queue/status` | GET | Current queue status |
| `/api/v1/frontend/config` | GET | Device-specific frontend config |

### Example API Usage

#### Submit a processing request:
```bash
curl -X POST http://localhost:8000/api/v1/process/grayscale \
  -F "image=@test.jpg" \
  -F "threads=4" \
  -F "runs=1"
```

Response:
```json
{
  "request_id": "abc123-def456-789",
  "service": "grayscale",
  "status": "queued",
  "poll_url": "/api/v1/status/abc123-def456-789",
  "parameters": {
    "threads": "4",
    "runs": "1"
  }
}
```

#### Check processing status:
```bash
curl http://localhost:8000/api/v1/status/abc123-def456-789
```

Response:
```json
{
  "request_id": "abc123-def456-789",
  "status": "completed",
  "download_url": "/api/v1/download/abc123-def456-789",
  "result_url": "/api/v1/result/abc123-def456-789"
}
```

## Scaling Configuration

The service scaler can be configured via environment variables:

```env
SCALE_CHECK_INTERVAL=30        # Check every 30 seconds
MAX_INSTANCES=5                # Maximum service instances
MIN_INSTANCES=1                # Minimum service instances
SCALE_UP_THRESHOLD=10          # Scale up when >10 messages/instance
SCALE_DOWN_THRESHOLD=2         # Scale down when <2 messages/instance
```

## API Gateway Scaling Configuration

The API Gateway scaling is configured differently from processing services:

```env
# API Gateway Scaling (load-based)
GATEWAY_MIN_INSTANCES=1              # Always keep at least 1 gateway
GATEWAY_MAX_INSTANCES=3              # Max 3 gateway instances
GATEWAY_LOAD_THRESHOLD_UP=80         # Scale up when load > 80%
GATEWAY_LOAD_THRESHOLD_DOWN=30       # Scale down when load < 30%
GATEWAY_COOLDOWN_PERIOD=180          # 3 minutes between scaling actions

# Processing Services Scaling (queue-based)
SERVICES_MIN_INSTANCES=1
SERVICES_MAX_INSTANCES=5
SCALE_UP_THRESHOLD=10                # Messages per instance
SCALE_DOWN_THRESHOLD=2               # Messages per instance
SERVICES_COOLDOWN_PERIOD=120         # 2 minutes between scaling actions
```

### Load Calculation for API Gateway

The load score is calculated as:
```
Load Score = (Average Queue Depth × 10) + (Response Time / 100)
```

Where:
- **Queue Depth**: Average across all service queues
- **Response Time**: API Gateway health check response time in ms
- **Score Range**: 0-100 (higher = more load)

### Scaling Events Timeline

1. **Scale Up Trigger**: Load > 80% for 30+ seconds
2. **Scaling Action**: Add new API Gateway instance
3. **Load Balancer Update**: Nginx configuration updated automatically
4. **Cooldown Period**: 180 seconds before next scaling decision
5. **Scale Down Trigger**: Load < 30% for 30+ seconds (after cooldown)

### Scaling Logic

- **Scale Up**: When `messages_in_queue / current_instances > SCALE_UP_THRESHOLD`
- **Scale Down**: When `messages_in_queue / current_instances < SCALE_DOWN_THRESHOLD`
- **Cooldown**: 120 seconds between scaling actions to prevent oscillation

## Device Adaptation

The frontend automatically adapts based on:

### Mobile Detection
- Simplified UI with fewer controls
- Touch-optimized interface
- Single file upload (no batch processing)
- Reduced polling frequency

### Bandwidth Detection
- Low bandwidth mode reduces UI complexity
- Longer polling intervals
- Compressed responses

### Configuration Example
```json
{
  "ui_mode": "mobile",
  "max_concurrent_uploads": 1,
  "polling_interval": 5000,
  "features": {
    "batch_processing": false,
    "real_time_preview": false,
    "advanced_metrics": false
  }
}
```

## Deployment and Usage

### 1. Start the complete stack:
```bash
cd event-driven
docker-compose up --build
```

### 2. Access the applications:
- **New Frontend (API Gateway)**: http://localhost:8080
- **Original Frontend**: http://localhost:8081 (for comparison)
- **API Gateway**: http://localhost:8000
- **Service Scaler Health**: http://localhost:8082/health

### 3. Monitor scaling:
- Prometheus metrics: http://localhost:9090/metrics (scaler)
- Prometheus metrics: http://localhost:8090/metrics (gateway)

### 4. Test with mobile simulation:
```bash
# Simulate mobile device
curl -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)" \
     http://localhost:8000/api/v1/frontend/config

# Simulate low bandwidth
curl "http://localhost:8000/api/v1/frontend/config?bandwidth=low"
```

## Benefits of This Architecture

### 1. **Separation of Concerns**
- Frontend focuses on user experience
- API Gateway handles service orchestration
- Processing services focus on computation
- Scaler manages infrastructure

### 2. **Scalability**
- Services scale independently based on demand
- Queue-based load balancing
- Automatic resource management

### 3. **Device Adaptation**
- Optimized experience for different devices
- Bandwidth-aware configurations
- Progressive enhancement

### 4. **Monitoring & Observability**
- Comprehensive health checks
- Prometheus metrics
- Queue depth monitoring
- Scaling events tracking

### 5. **Future Extensibility**
- Easy to add new processing services
- Service discovery pattern
- Pluggable frontend components

## Adding New Processing Services

To add a new service (e.g., "sobel" edge detection):

1. **Create the service** following the `grayscale_service` pattern
2. **Update API Gateway** service registry:
```python
SERVICES = {
    'grayscale': { ... },
    'sobel': {
        'queue': 'sobel_processing',
        'endpoint': 'http://sobel_service:8002',
        'description': 'Apply Sobel edge detection filter'
    }
}
```
3. **Add to docker-compose.yml**
4. **Update scaler configuration** to include the new service

## Monitoring and Troubleshooting

### Check System Health
```bash
curl http://localhost:8000/api/v1/health
```

### Monitor Queue Depths
```bash
curl http://localhost:8000/api/v1/queue/status
```

### Check Scaling Status
```bash
curl http://localhost:8082/health
```

### View Prometheus Metrics
- Gateway metrics: http://localhost:8090/metrics
- Scaler metrics: http://localhost:9090/metrics

## Storage Architecture Options

The system supports two storage architecture patterns:

### Option 1: Centralized Storage
```
All Services → Single MinIO Instance
```
**Advantages:**
- Simpler architecture and configuration
- Easier backup and restore operations
- Lower resource requirements
- Single source of truth for all data

**Disadvantages:**
- Single point of failure
- Potential performance bottleneck
- Limited scalability for high-volume processing

### Option 2: Distributed Storage
```
Service 1 → MinIO Instance 1 ↔ Sync ↔ MinIO Instance 2 ← Service 2
                              ↓
                         Global MinIO Instance
```
**Advantages:**
- Higher availability and fault tolerance
- Better performance distribution
- Service-specific storage optimization
- Horizontal scalability

**Disadvantages:**
- More complex synchronization logic
- Higher resource requirements
- Data consistency challenges
- More complex backup strategy

### Storage Synchronization
For distributed storage, implement:
- **Async Replication**: MinIO built-in replication between instances
- **Event-driven Sync**: Use RabbitMQ events to trigger cross-instance sync
- **Global Registry**: Central metadata storage for cross-service file references

This architecture provides a robust, scalable foundation for your image processing system that can adapt to different devices and automatically scale based on demand.
