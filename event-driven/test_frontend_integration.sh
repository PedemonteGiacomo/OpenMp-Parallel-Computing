#!/bin/bash

echo "🧪 Testing Frontend Integration"
echo "=================================="

# Test that frontend loads
echo "1. Testing frontend accessibility..."
FRONTEND_RESPONSE=$(curl -s -I http://localhost:8081/ | head -n 1)
if [[ $FRONTEND_RESPONSE == *"200"* ]]; then
    echo "✅ Frontend is accessible on port 8081"
else
    echo "❌ Frontend not accessible: $FRONTEND_RESPONSE"
    exit 1
fi

# Test API Gateway through Nginx
echo "2. Testing API Gateway through Nginx..."
API_RESPONSE=$(curl -s http://localhost:8000/api/v1/health)
if [[ $API_RESPONSE == *"healthy"* ]]; then
    echo "✅ API Gateway is healthy through Nginx (port 8000)"
else
    echo "❌ API Gateway not healthy: $API_RESPONSE"
    exit 1
fi

echo ""
echo "🎉 Frontend Integration Test Completed!"
echo "=================================="
echo "✅ Frontend UI: http://localhost:8081"
echo "✅ API Gateway: http://localhost:8000/api/v1/*"
echo ""
echo "To test the complete workflow:"
echo "1. Open http://localhost:8081 in your browser"
echo "2. Upload an image using the form"
echo "3. Wait for processing to complete"
echo "4. View and download the processed image"
echo ""
echo "The frontend will automatically:"
echo "- Submit images through the API Gateway"  
echo "- Poll for processing status"
echo "- Display the processed image inline"
echo "- Provide download functionality"
