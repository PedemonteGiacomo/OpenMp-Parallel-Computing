# Improved Event-Driven Architecture for Scaling to N Algorithms

## Current Issues
1. **Queue Inconsistency**: Frontend publishes to `grayscale` queue, but API Gateway publishes to `image_processing`
2. **No Result Delivery**: Processed images don't reach the frontend UI
3. **Hard to Scale**: Each algorithm needs its own result queue and frontend integration

## Proposed Architecture

### Queue Design
```
Input Queues (per algorithm):
├── image_processing (grayscale)
├── sobel_processing (sobel filter)  
├── blur_processing (gaussian blur)
└── [algorithm]_processing

Unified Results Queue:
└── processing_results (all algorithms publish here)

Status Tracking:
└── In-memory store in API Gateway (Redis in production)
```

### Message Flow
1. **Request**: UI → API Gateway → `[algorithm]_processing` queue
2. **Processing**: Algorithm Service consumes → processes → publishes to `processing_results`
3. **Response**: Frontend polls API Gateway for status updates
4. **Scaling**: Scaler monitors all `*_processing` queues

### Message Formats

#### Request Message (to algorithm queue)
```json
{
  "request_id": "uuid4",
  "algorithm": "grayscale",
  "image_key": "s3_key",
  "parameters": {
    "threads": 4,
    "runs": 1
  },
  "timestamp": "2025-06-27T11:00:00Z",
  "callback_info": {
    "result_queue": "processing_results",
    "status_url": "/api/v1/status/{request_id}"
  }
}
```

#### Result Message (to results queue)
```json
{
  "request_id": "uuid4",
  "algorithm": "grayscale", 
  "status": "completed|failed",
  "result": {
    "output_image_key": "processed_s3_key",
    "processing_time": 1.234,
    "metadata": {
      "threads_used": 4,
      "kernel_time": 0.987,
      "memory_used": "45MB"
    }
  },
  "error": null,
  "timestamp": "2025-06-27T11:00:05Z"
}
```

## Benefits
1. **Unified Interface**: Single results queue for all algorithms
2. **Easy Scaling**: Add new algorithms by adding new input queues
3. **Better Monitoring**: Centralized status tracking
4. **Consistent UX**: Same polling mechanism for all algorithms
5. **Fault Tolerance**: Results survive service restarts

## Implementation Steps
1. Update grayscale service to publish to unified `processing_results` queue
2. Create results consumer in API Gateway to update request status
3. Update frontend to poll API Gateway status endpoint instead of consuming directly
4. Add support for multiple algorithms in API Gateway configuration
5. Update scaler to monitor multiple queues
