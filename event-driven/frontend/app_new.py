import os
import logging
import requests
from flask import Flask, request, render_template_string, jsonify, redirect, url_for

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# API Gateway configuration (internal URL for server-side requests)
API_GATEWAY_URL = os.environ.get('API_GATEWAY_URL', 'http://api_gateway:8000')

# HTML template
PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Image Processing Service</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <!-- Materialize CSS -->
    <link href="https://cdnjs.cloudflare.com/ajax/libs/materialize/1.0.0/css/materialize.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <!-- Chart.js -->
    <script src="{{ url_for('static', filename='chart.min.js') }}"></script>
    <style>
        .container { margin-top: 20px; }
        .progress-container { margin: 20px 0; }
        .result-container { margin-top: 30px; }
        .image-card { margin: 10px 0; }
        .download-btn { margin-top: 10px; }
        #processed-img { max-width: 100%; height: auto; }
        .error-message { color: #f44336; margin: 10px 0; }
    </style>
</head>
<body>
    <!-- Materialize JS -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/materialize/1.0.0/js/materialize.min.js"></script>

    <div class="container">
        <h1 class="center-align">OpenMP Image Processing</h1>
        
        <div class="row">
            <div class="col s12 m8 offset-m2">
                <div class="card">
                    <div class="card-content">
                        <span class="card-title">Upload Image for Processing</span>
                        
                        <form id="upload-form" enctype="multipart/form-data">
                            <div class="file-field input-field">
                                <div class="btn">
                                    <span>Choose Image</span>
                                    <input type="file" name="image" accept="image/*" required>
                                </div>
                                <div class="file-path-wrapper">
                                    <input class="file-path validate" type="text" placeholder="Upload an image">
                                </div>
                            </div>
                            
                            <p>Thread configuration:</p>
                            <div class="input-field">
                                <select name="threads" multiple>
                                    <option value="1" selected>1 Thread</option>
                                    <option value="2" selected>2 Threads</option>
                                    <option value="4" selected>4 Threads</option>
                                    <option value="6">6 Threads</option>
                                    <option value="8">8 Threads</option>
                                </select>
                                <label>Threads to test</label>
                            </div>
                            
                            <div class="input-field">
                                <input id="repeat" type="number" name="repeat" min="1" value="3">
                                <label for="repeat">Runs per thread</label>
                            </div>
                            
                            <div class="input-field">
                                <input id="passes" type="number" name="passes" min="1" value="1">
                                <label for="passes">Passes (complexity)</label>
                            </div>
                            
                            <button class="btn waves-effect waves-light blue" type="submit">
                                Process Image
                                <i class="material-icons right">send</i>
                            </button>
                        </form>
                    </div>
                </div>
            </div>
        </div>

        <!-- Progress and Results Section -->
        <div id="results-section" style="display: none;">
            <div class="row">
                <div class="col s12">
                    <div class="card">
                        <div class="card-content">
                            <span class="card-title">Processing Status</span>
                            
                            <div class="progress-container">
                                <div id="status-text">Uploading...</div>
                                <div class="progress">
                                    <div id="progress-bar" class="determinate" style="width: 0%"></div>
                                </div>
                            </div>
                            
                            <div id="error-container" class="error-message" style="display: none;"></div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Results Display -->
            <div id="results-display" class="result-container" style="display: none;">
                <div class="row">
                    <div class="col s12 m6">
                        <div class="card image-card">
                            <div class="card-image">
                                <img id="original-img" class="materialboxed" alt="Original Image">
                                <span class="card-title">Original Image</span>
                            </div>
                        </div>
                    </div>
                    <div class="col s12 m6">
                        <div class="card image-card">
                            <div class="card-image">
                                <img id="processed-img" class="materialboxed" alt="Processed Image">
                                <span class="card-title">Processed Image</span>
                            </div>
                            <div class="card-action">
                                <a id="download-btn" class="btn green download-btn" href="#" download>
                                    <i class="material-icons left">download</i>Download
                                </a>
                                <a id="view-btn" class="btn blue" href="#" target="_blank">
                                    <i class="material-icons left">open_in_new</i>View Full Size
                                </a>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Performance Charts -->
                <div class="row">
                    <div class="col s12 m6">
                        <div class="card">
                            <div class="card-content">
                                <span class="card-title">Execution Time</span>
                                <canvas id="timeChart" height="200"></canvas>
                            </div>
                        </div>
                    </div>
                    <div class="col s12 m6">
                        <div class="card">
                            <div class="card-content">
                                <span class="card-title">Speedup</span>
                                <canvas id="speedChart" height="200"></canvas>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Initialize Materialize components
        document.addEventListener('DOMContentLoaded', function() {
            M.AutoInit();
        });

        // Global variables for charts
        let timeChart, speedChart;
        let currentRequestId = null;
        let statusPollInterval = null;

        // Form submission handler
        document.getElementById('upload-form').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            const threads = Array.from(document.querySelectorAll('select[name="threads"] option:checked')).map(opt => parseInt(opt.value));
            
            // Build the payload
            const payload = new FormData();
            payload.append('image', formData.get('image'));
            payload.append('threads', JSON.stringify(threads));
            payload.append('repeat', formData.get('repeat'));
            payload.append('passes', formData.get('passes'));

            // Show results section and hide form
            document.getElementById('results-section').style.display = 'block';
            document.getElementById('results-display').style.display = 'none';
            document.getElementById('error-container').style.display = 'none';
            
            updateStatus('Uploading image...', 10);

            try {
                // Submit to API Gateway
                const response = await fetch('/api/v1/process/grayscale', {
                    method: 'POST',
                    body: payload
                });

                if (!response.ok) {
                    throw new Error(`Upload failed: ${response.status} ${response.statusText}`);
                }

                const result = await response.json();
                currentRequestId = result.request_id;
                
                updateStatus('Image uploaded successfully. Processing...', 30);
                startStatusPolling();
                
            } catch (error) {
                console.error('Upload error:', error);
                showError(`Upload failed: ${error.message}`);
            }
        });

        function updateStatus(message, progress) {
            document.getElementById('status-text').textContent = message;
            document.getElementById('progress-bar').style.width = progress + '%';
        }

        function showError(message) {
            document.getElementById('error-container').textContent = message;
            document.getElementById('error-container').style.display = 'block';
            updateStatus('Error occurred', 100);
            if (statusPollInterval) {
                clearInterval(statusPollInterval);
            }
        }

        function startStatusPolling() {
            if (statusPollInterval) {
                clearInterval(statusPollInterval);
            }
            
            statusPollInterval = setInterval(pollStatus, 2000);
            pollStatus(); // Initial poll
        }

        async function pollStatus() {
            if (!currentRequestId) return;

            try {
                const response = await fetch(`/api/v1/status/${currentRequestId}`);
                
                if (!response.ok) {
                    throw new Error(`Status check failed: ${response.status}`);
                }

                const status = await response.json();
                
                switch (status.status) {
                    case 'queued':
                        updateStatus('Request queued, waiting for processing...', 40);
                        break;
                    case 'processing':
                        updateStatus('Processing image...', 60);
                        break;
                    case 'completed':
                        updateStatus('Processing completed!', 100);
                        displayResults(status);
                        clearInterval(statusPollInterval);
                        break;
                    case 'failed':
                        showError(`Processing failed: ${status.error || 'Unknown error'}`);
                        clearInterval(statusPollInterval);
                        break;
                    default:
                        updateStatus('Processing...', 50);
                }
                
            } catch (error) {
                console.error('Status polling error:', error);
                showError(`Status check failed: ${error.message}`);
                clearInterval(statusPollInterval);
            }
        }

        function displayResults(status) {
            // Show the original image (if available)
            if (status.input_object) {
                document.getElementById('original-img').src = `/api/v1/image/${currentRequestId}?type=input`;
            }
            
            // Show the processed image
            document.getElementById('processed-img').src = status.image_url;
            
            // Set up download and view buttons
            document.getElementById('download-btn').href = status.download_url;
            document.getElementById('view-btn').href = status.image_url;
            
            // Show results
            document.getElementById('results-display').style.display = 'block';
            
            // Re-initialize Materialize image box
            M.Materialbox.init(document.querySelectorAll('.materialboxed'));
            
            // Display performance charts if available
            if (status.performance_data || status.times) {
                displayCharts(status);
            }
        }

        function displayCharts(status) {
            // Extract performance data
            const times = status.times || status.performance_data?.times || {};
            const threads = Object.keys(times).map(t => parseInt(t)).sort((a,b) => a-b);
            
            if (threads.length === 0) return;
            
            // Prepare data for charts
            const totalTimes = threads.map(t => times[t].total || times[t] || 0);
            const kernelTimes = threads.map(t => times[t].kernel || 0);
            
            // Create time chart
            const timeCtx = document.getElementById('timeChart').getContext('2d');
            timeChart = new Chart(timeCtx, {
                type: 'bar',
                data: {
                    labels: threads.map(t => t + ' threads'),
                    datasets: [{
                        label: 'Total Time (ms)',
                        data: totalTimes,
                        backgroundColor: 'rgba(54, 162, 235, 0.6)',
                        borderColor: 'rgba(54, 162, 235, 1)',
                        borderWidth: 1
                    }, {
                        label: 'Kernel Time (ms)',
                        data: kernelTimes,
                        backgroundColor: 'rgba(255, 99, 132, 0.6)',
                        borderColor: 'rgba(255, 99, 132, 1)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Time (ms)'
                            }
                        }
                    }
                }
            });
            
            // Create speedup chart
            const speedCtx = document.getElementById('speedChart').getContext('2d');
            const baseTotalTime = totalTimes[0] || 1;
            const baseKernelTime = kernelTimes[0] || 1;
            
            const totalSpeedup = totalTimes.map(time => time > 0 ? baseTotalTime / time : 0);
            const kernelSpeedup = kernelTimes.map(time => time > 0 ? baseKernelTime / time : 0);
            
            speedChart = new Chart(speedCtx, {
                type: 'line',
                data: {
                    labels: threads.map(t => t + ' threads'),
                    datasets: [{
                        label: 'Total Speedup',
                        data: totalSpeedup,
                        borderColor: 'rgba(54, 162, 235, 1)',
                        backgroundColor: 'rgba(54, 162, 235, 0.1)',
                        tension: 0.1
                    }, {
                        label: 'Kernel Speedup',
                        data: kernelSpeedup,
                        borderColor: 'rgba(255, 99, 132, 1)',
                        backgroundColor: 'rgba(255, 99, 132, 0.1)',
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: 'Speedup Factor'
                            }
                        }
                    }
                }
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Main page with image upload form"""
    return render_template_string(PAGE_TEMPLATE)

@app.route('/api/v1/process/<service_name>', methods=['POST'])
def proxy_process(service_name):
    """Proxy process requests to API Gateway"""
    try:
        # Forward the request to the API Gateway
        files = {}
        if 'image' in request.files:
            files['image'] = (
                request.files['image'].filename,
                request.files['image'].stream,
                request.files['image'].content_type
            )
        
        # Forward other form data
        data = {}
        for key, value in request.form.items():
            data[key] = value
            
        response = requests.post(
            f"{API_GATEWAY_URL}/api/v1/process/{service_name}",
            files=files,
            data=data,
            timeout=30
        )
        
        # Return the response from API Gateway
        return response.json(), response.status_code
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error proxying request to API Gateway: {e}")
        return {"error": "Service temporarily unavailable"}, 503

@app.route('/api/v1/status/<request_id>')
def proxy_status(request_id):
    """Proxy status requests to API Gateway"""
    try:
        response = requests.get(f"{API_GATEWAY_URL}/api/v1/status/{request_id}", timeout=10)
        return response.json(), response.status_code
    except requests.exceptions.RequestException as e:
        logger.error(f"Error proxying status request to API Gateway: {e}")
        return {"error": "Service temporarily unavailable"}, 503

@app.route('/api/v1/download/<request_id>')
def proxy_download(request_id):
    """Proxy download requests to API Gateway"""
    try:
        response = requests.get(f"{API_GATEWAY_URL}/api/v1/download/{request_id}", stream=True, timeout=30)
        
        if response.status_code != 200:
            return response.json(), response.status_code
            
        # Create a Flask response from the streamed content
        from flask import Response
        return Response(
            response.iter_content(chunk_size=8192),
            content_type=response.headers.get('content-type'),
            headers={
                'Content-Disposition': response.headers.get('content-disposition', f'attachment; filename="processed_{request_id}.png"')
            }
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Error proxying download request to API Gateway: {e}")
        return {"error": "Service temporarily unavailable"}, 503

@app.route('/api/v1/image/<request_id>')
def proxy_image(request_id):
    """Proxy image view requests to API Gateway"""
    try:
        # Forward query parameters (like type=input)
        params = dict(request.args)
        
        response = requests.get(
            f"{API_GATEWAY_URL}/api/v1/image/{request_id}",
            params=params,
            stream=True,
            timeout=30
        )
        
        if response.status_code != 200:
            return response.json(), response.status_code
            
        # Create a Flask response from the streamed content
        from flask import Response
        return Response(
            response.iter_content(chunk_size=8192),
            content_type=response.headers.get('content-type', 'image/png')
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Error proxying image request to API Gateway: {e}")
        return {"error": "Service temporarily unavailable"}, 503

@app.route('/health')
def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "frontend"}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
