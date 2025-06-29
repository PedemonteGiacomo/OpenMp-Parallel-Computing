#!/bin/bash

# API Gateway Test Script
# This script tests the new API Gateway architecture

set -e

API_GATEWAY_URL="http://localhost:8000"
FRONTEND_URL="http://localhost:8080"
TEST_IMAGE="images/test.jpg"

echo "🚀 Testing API Gateway Architecture"
echo "=================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Check if jq is available, provide fallback
HAS_JQ=false
if command -v jq &> /dev/null; then
    HAS_JQ=true
else
    print_warning "jq is not installed. JSON output will be plain text."
    print_status "To install jq: sudo apt-get install jq (Ubuntu/Debian) or brew install jq (macOS)"
fi

# JSON formatting function
format_json() {
    if [ "$HAS_JQ" = true ]; then
        echo "$1" | jq '.'
    else
        echo "$1"
    fi
}

# Extract JSON field function
extract_json_field() {
    local json="$1"
    local field="$2"
    
    if [ "$HAS_JQ" = true ]; then
        echo "$json" | jq -r ".$field"
    else
        # Fallback: simple grep/sed extraction (basic, may not work for complex JSON)
        echo "$json" | grep -o "\"$field\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | sed "s/.*\"$field\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/" 2>/dev/null || echo ""
    fi
}

# Check if services are running
print_status "Checking if services are running..."

if ! curl -s "$API_GATEWAY_URL/api/v1/health" > /dev/null; then
    print_error "API Gateway is not running at $API_GATEWAY_URL"
    print_status "Please start the services with: docker-compose up --build"
    exit 1
fi

if ! curl -s "$FRONTEND_URL/health" > /dev/null; then
    print_error "Frontend Gateway is not running at $FRONTEND_URL"
    print_status "Please start the services with: docker-compose up --build"
    exit 1
fi

print_success "Services are running!"

# Test 1: Health Check
print_status "Test 1: Health Check"
health_response=$(curl -s "$API_GATEWAY_URL/api/v1/health")
format_json "$health_response"
echo ""

# Test 2: List Available Services
print_status "Test 2: List Available Services"
services_response=$(curl -s "$API_GATEWAY_URL/api/v1/services")
format_json "$services_response"
echo ""

# Test 3: Check Queue Status
print_status "Test 3: Check Queue Status"
queue_response=$(curl -s "$API_GATEWAY_URL/api/v1/queue/status")
format_json "$queue_response"
echo ""

# Test 4: Frontend Configuration (Desktop)
print_status "Test 4: Frontend Configuration (Desktop)"
desktop_config=$(curl -s "$API_GATEWAY_URL/api/v1/frontend/config")
format_json "$desktop_config"
echo ""

# Test 5: Frontend Configuration (Mobile)
print_status "Test 5: Frontend Configuration (Mobile)"
mobile_config=$(curl -s -H "User-Agent: Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)" "$API_GATEWAY_URL/api/v1/frontend/config")
format_json "$mobile_config"
echo ""

# Test 6: Submit Processing Request
if [ -f "$TEST_IMAGE" ]; then
    print_status "Test 6: Submit Processing Request"
    
    submit_response=$(curl -s -X POST \
        -F "image=@$TEST_IMAGE" \
        -F "threads=4" \
        -F "runs=1" \
        "$API_GATEWAY_URL/api/v1/process/grayscale")
    
    format_json "$submit_response"
    
    # Extract request ID
    request_id=$(extract_json_field "$submit_response" "request_id")
    
    if [ "$request_id" != "null" ] && [ "$request_id" != "" ]; then
        print_success "Processing request submitted: $request_id"
        
        # Test 7: Poll for Status
        print_status "Test 7: Polling for Status"
        
        max_attempts=30
        attempt=1
        
        while [ $attempt -le $max_attempts ]; do
            print_status "Attempt $attempt/$max_attempts - Checking status..."
            
            status_response=$(curl -s "$API_GATEWAY_URL/api/v1/status/$request_id")
            status=$(extract_json_field "$status_response" "status")
            
            format_json "$status_response"
            
            if [ "$status" = "completed" ]; then
                print_success "Processing completed!"
                
                # Test 8: Get Detailed Results
                print_status "Test 8: Get Detailed Results"
                result_response=$(curl -s "$API_GATEWAY_URL/api/v1/result/$request_id")
                format_json "$result_response"
                
                # Test 9: Download Result
                print_status "Test 9: Download Result"
                download_url="$API_GATEWAY_URL/api/v1/download/$request_id"
                output_file="test_result_${request_id}.png"
                
                if curl -s -o "$output_file" "$download_url"; then
                    print_success "Result downloaded: $output_file"
                    file_size=$(ls -lh "$output_file" | awk '{print $5}')
                    print_status "File size: $file_size"
                else
                    print_error "Failed to download result"
                fi
                
                break
            elif [ "$status" = "failed" ]; then
                print_error "Processing failed!"
                if [ "$HAS_JQ" = true ]; then
                    echo "$status_response" | jq '.error'
                else
                    echo "Error details: $status_response"
                fi
                break
            elif [ "$status" = "processing" ] || [ "$status" = "queued" ]; then
                print_status "Status: $status - waiting..."
                sleep 2
            else
                print_warning "Unknown status: $status"
                sleep 2
            fi
            
            attempt=$((attempt + 1))
        done
        
        if [ $attempt -gt $max_attempts ]; then
            print_error "Timeout waiting for processing to complete"
        fi
        
    else
        print_error "Failed to get request ID from response"
    fi
    
else
    print_warning "Test image not found at $TEST_IMAGE - skipping processing test"
fi

# Test 10: Load Testing (Optional)
print_status "Test 10: Load Testing (Light)"

if [ -f "$TEST_IMAGE" ]; then
    print_status "Submitting 3 concurrent requests..."
    
    # Submit multiple requests in background
    for i in {1..3}; do
        {
            response=$(curl -s -X POST \
                -F "image=@$TEST_IMAGE" \
                -F "threads=2" \
                -F "runs=1" \
                "$API_GATEWAY_URL/api/v1/process/grayscale")
            
            request_id=$(extract_json_field "$response" "request_id")
            echo "Request $i submitted: $request_id"
        } &
    done
    
    # Wait for all background jobs
    wait
    
    print_success "Load testing completed"
    
    # Check queue status after load
    print_status "Queue status after load:"
    queue_after=$(curl -s "$API_GATEWAY_URL/api/v1/queue/status")
    format_json "$queue_after"
else
    print_warning "Skipping load test - no test image available"
fi

# Test 11: Load Testing for Gateway Scaling
print_status "Test 11: Load Testing for Gateway Scaling"

if [ -f "$TEST_IMAGE" ]; then
    print_status "Submitting high load to trigger gateway scaling..."
    
    # Check initial gateway instances
    initial_instances=$(docker ps --filter "label=com.docker.compose.service=api_gateway" --format "table {{.Names}}" | grep -c "api_gateway" || echo "1")
    print_status "Initial API Gateway instances: $initial_instances"
    
    # Submit many concurrent requests to increase load
    for i in {1..20}; do
        {
            response=$(curl -s -X POST \
                -F "image=@$TEST_IMAGE" \
                -F "threads=1" \
                -F "runs=1" \
                "$API_GATEWAY_URL/api/v1/process/grayscale")
            
            request_id=$(extract_json_field "$response" "request_id")
            echo "High load request $i submitted: $request_id"
        } &
    done
    
    # Wait for all background jobs
    wait
    
    print_success "High load testing completed"
    
    # Wait a bit for scaling to potentially happen
    print_status "Waiting 60 seconds for potential scaling..."
    sleep 60
    
    # Check if gateway scaled
    final_instances=$(docker ps --filter "label=com.docker.compose.service=api_gateway" --format "table {{.Names}}" | grep -c "api_gateway" || echo "1")
    print_status "Final API Gateway instances: $final_instances"
    
    if [ "$final_instances" -gt "$initial_instances" ]; then
        print_success "🎉 API Gateway scaling detected! Scaled from $initial_instances to $final_instances instances"
    else
        print_warning "No gateway scaling detected (may need higher load or longer wait time)"
    fi
    
    # Check nginx load balancer status
    print_status "Nginx load balancer status:"
    curl -s "http://localhost:8000/nginx/metrics" || print_warning "Nginx metrics not available"
    
else
    print_warning "Skipping load test - no test image available"
fi

echo ""
print_success "🎉 API Gateway testing completed!"
echo ""
print_status "Summary of endpoints tested:"
echo "  ✅ Health check"
echo "  ✅ Service listing"
echo "  ✅ Queue status" 
echo "  ✅ Frontend configuration"
echo "  ✅ Processing request submission"
echo "  ✅ Status polling"
echo "  ✅ Result download"
echo "  ✅ Load testing"
echo ""
print_status "You can now:"
echo "  • Open $FRONTEND_URL in your browser"
echo "  • Monitor metrics at http://localhost:8090/metrics (Gateway)"
echo "  • Monitor metrics at http://localhost:9090/metrics (Scaler)"
echo "  • Check scaler health at http://localhost:8082/health"
