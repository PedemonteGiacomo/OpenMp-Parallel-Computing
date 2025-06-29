#!/bin/bash

# Scalable API Gateway Event-Driven Architecture Startup Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

print_banner() {
    echo -e "${PURPLE}"
    echo "╔══════════════════════════════════════════════════════════════════╗"
    echo "║                 Scalable API Gateway Architecture                ║"
    echo "║              Event-Driven Image Processing System                ║"
    echo "║                  With Auto-Scaling Gateway                       ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_usage() {
    echo "Usage: $0 [centralized|distributed]"
    echo ""
    echo "Storage Architecture Options:"
    echo "  centralized  - Single MinIO instance (default)"
    echo "  distributed  - Multiple MinIO instances with sync"
    echo ""
    echo "Examples:"
    echo "  $0                  # Start with centralized storage"
    echo "  $0 centralized      # Start with centralized storage"
    echo "  $0 distributed      # Start with distributed storage"
}

ARCHITECTURE="${1:-centralized}"

if [[ "$ARCHITECTURE" != "centralized" && "$ARCHITECTURE" != "distributed" ]]; then
    print_error "Invalid architecture: $ARCHITECTURE"
    show_usage
    exit 1
fi

print_banner

print_status "Starting Scalable API Gateway Architecture with $ARCHITECTURE storage..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker first."
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    print_error "docker-compose is not installed. Please install docker-compose."
    exit 1
fi

# Stop any existing containers
print_status "Stopping any existing containers..."
docker-compose down --remove-orphans > /dev/null 2>&1 || true
if [ "$ARCHITECTURE" = "distributed" ]; then
    docker-compose -f docker-compose.distributed.yml down --remove-orphans > /dev/null 2>&1 || true
fi

# Build and start services
print_status "Building and starting services with $ARCHITECTURE storage..."
print_warning "This may take a few minutes on first run..."

COMPOSE_FILE="docker-compose.yml"
if [ "$ARCHITECTURE" = "distributed" ]; then
    COMPOSE_FILE="docker-compose.distributed.yml"
fi

if docker-compose -f "$COMPOSE_FILE" up --build -d; then
    print_success "Services started successfully with $ARCHITECTURE storage!"
else
    print_error "Failed to start services. Check the logs with: docker-compose -f $COMPOSE_FILE logs"
    exit 1
fi

# Wait for services to be ready
print_status "Waiting for services to be ready..."

max_attempts=60
attempt=1

while [ $attempt -le $max_attempts ]; do
    if curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        print_success "API Gateway is ready!"
        break
    fi
    
    echo -n "."
    sleep 2
    attempt=$((attempt + 1))
done

echo ""

if [ $attempt -gt $max_attempts ]; then
    print_error "Timeout waiting for services to be ready"
    print_status "Check logs with: docker-compose logs"
    exit 1
fi

# Display service status
print_status "Service Status:"
echo ""

services=(
    "nginx_lb:8000:/nginx/health:Load Balancer"
    "api_gateway:8000:/api/v1/health:API Gateway"
    "frontend_gateway:8080:/health:Frontend (New)"
    "service_scaler:8082:/health:Service Scaler"
)

# Add storage-specific services
if [ "$ARCHITECTURE" = "distributed" ]; then
    services+=(
        "storage_sync:8080:/health:Storage Sync"
        "minio_global:9000::Global Storage"
        "minio_service1:9010::Service 1 Storage"
        "minio_service2:9020::Service 2 Storage"
    )
else
    services+=(
        "minio:9000::MinIO Storage"
    )
fi

for service in "${services[@]}"; do
    IFS=':' read -r name port endpoint description <<< "$service"
    
    if [ -n "$endpoint" ]; then
        if curl -s "http://localhost:${port}${endpoint}" > /dev/null 2>&1; then
            echo -e "  ✅ ${GREEN}${description}${NC} - http://localhost:${port}"
        else
            echo -e "  ❌ ${RED}${description}${NC} - http://localhost:${port} (Not ready)"
        fi
    else
        # For services without health endpoint, just check if port is open
        if nc -z localhost "$port" 2>/dev/null; then
            echo -e "  ✅ ${GREEN}${description}${NC} - http://localhost:${port}"
        else
            echo -e "  ❌ ${RED}${description}${NC} - http://localhost:${port} (Not ready)"
        fi
    fi
done

echo ""

# Show queue status
print_status "Queue Status:"
queue_response=$(curl -s http://localhost:8000/api/v1/queue/status 2>/dev/null || echo '{"error": "not ready"}')
if echo "$queue_response" | grep -q "error"; then
    echo "  Queue information not available yet"
else
    echo "$queue_response" | jq '.queues' 2>/dev/null || echo "  Queue data available via API"
fi

echo ""

# Display access information
print_success "🚀 Scalable System is ready with $ARCHITECTURE storage!"
echo ""
echo -e "${YELLOW}Access URLs:${NC}"
echo -e "  🌐 ${GREEN}Main Frontend (Load Balanced):${NC}  http://localhost:8080"
echo -e "  🔧 ${PURPLE}API Gateway (Load Balanced):${NC}   http://localhost:8000"
echo -e "  📊 ${YELLOW}Service Scaler:${NC}               http://localhost:8082"
echo ""
echo -e "${YELLOW}Load Balancer & Scaling:${NC}"
echo -e "  ⚖️  ${GREEN}Nginx Load Balancer:${NC}           http://localhost:8000/nginx/health"
echo -e "  📈 ${GREEN}Nginx Metrics:${NC}                 http://localhost:8000/nginx/metrics"
echo -e "  � ${BLUE}API Gateway Scaling:${NC}           1-3 instances (load-based)"
echo -e "  🔄 ${BLUE}Service Scaling:${NC}               1-5 instances (queue-based)"
echo ""
if [ "$ARCHITECTURE" = "distributed" ]; then
    echo -e "${YELLOW}Distributed Storage:${NC}"
    echo -e "  🗄️  ${GREEN}Global Storage:${NC}                http://localhost:9000"
    echo -e "  �️  ${GREEN}Service 1 Storage:${NC}             http://localhost:9010"
    echo -e "  🗄️  ${GREEN}Service 2 Storage:${NC}             http://localhost:9020"
    echo -e "  🔄 ${BLUE}Storage Sync Service:${NC}          http://localhost:8080 (storage_sync)"
else
    echo -e "${YELLOW}Centralized Storage:${NC}"
    echo -e "  🗄️  ${GREEN}MinIO Storage:${NC}                 http://localhost:9000"
fi
echo ""
echo -e "${YELLOW}Monitoring URLs:${NC}"
echo -e "  📈 ${GREEN}Prometheus (Gateway):${NC}          http://localhost:8090/metrics"
echo -e "  📈 ${GREEN}Prometheus (Scaler):${NC}           http://localhost:9090/metrics"
if [ "$ARCHITECTURE" = "distributed" ]; then
    echo -e "  📈 ${GREEN}Prometheus (Storage Sync):${NC}     http://localhost:9090/metrics (storage_sync)"
fi
echo -e "  🏥 ${BLUE}System Health:${NC}                  http://localhost:8000/api/v1/health"
echo ""
echo -e "${YELLOW}Useful Commands:${NC}"
echo -e "  🧪 ${GREEN}Test System:${NC}                   ./test_api_gateway.sh"
echo -e "  📊 ${GREEN}View Logs:${NC}                     docker-compose -f $COMPOSE_FILE logs -f"
echo -e "  🛑 ${RED}Stop Services:${NC}                 docker-compose -f $COMPOSE_FILE down"
echo -e "  🔄 ${YELLOW}Restart Services:${NC}              docker-compose -f $COMPOSE_FILE restart"
echo ""

# Check if test script exists and is executable
if [ -f "test_api_gateway.sh" ] && [ -x "test_api_gateway.sh" ]; then
    read -p "Would you like to run the API Gateway test script? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_status "Running API Gateway tests..."
        ./test_api_gateway.sh
    fi
else
    print_warning "Test script not found or not executable. You can run it manually with: ./test_api_gateway.sh"
fi

print_success "Setup complete! Your API Gateway architecture is ready to use."
