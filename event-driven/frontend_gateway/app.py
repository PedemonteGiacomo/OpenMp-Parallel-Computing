import os
import time
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

# Configuration
API_GATEWAY_URL = os.environ.get('API_GATEWAY_URL', 'http://api_gateway:8000')

class APIGatewayClient:
    def __init__(self, base_url):
        self.base_url = base_url
        
    def get_services(self):
        """Get available processing services"""
        try:
            response = requests.get(f"{self.base_url}/api/v1/services", timeout=10)
            if response.status_code == 200:
                return response.json()
            return {'services': {}, 'total_services': 0}
        except Exception as e:
            logger.error(f"Error getting services: {e}")
            return {'services': {}, 'total_services': 0}
    
    def get_frontend_config(self, user_agent=None, bandwidth=None):
        """Get device-specific frontend configuration"""
        try:
            headers = {}
            if user_agent:
                headers['User-Agent'] = user_agent
                
            params = {}
            if bandwidth:
                params['bandwidth'] = bandwidth
                
            response = requests.get(
                f"{self.base_url}/api/v1/frontend/config",
                headers=headers,
                params=params,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return self._default_config()
        except Exception as e:
            logger.error(f"Error getting frontend config: {e}")
            return self._default_config()
    
    def _default_config(self):
        return {
            'ui_mode': 'desktop',
            'max_concurrent_uploads': 3,
            'polling_interval': 2000,
            'features': {
                'batch_processing': True,
                'real_time_preview': True,
                'advanced_metrics': True
            },
            'services': ['grayscale']
        }
    
    def submit_processing_request(self, service_name, file, threads=4, runs=1):
        """Submit an image processing request"""
        try:
            files = {'image': file}
            data = {
                'threads': str(threads),
                'runs': str(runs)
            }
            
            response = requests.post(
                f"{self.base_url}/api/v1/process/{service_name}",
                files=files,
                data=data,
                timeout=30
            )
            
            if response.status_code in [200, 202]:
                return response.json()
            else:
                return {'error': f'Server returned status {response.status_code}'}
                
        except Exception as e:
            logger.error(f"Error submitting processing request: {e}")
            return {'error': str(e)}
    
    def get_status(self, request_id):
        """Get processing status"""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/status/{request_id}",
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return {'status': 'unknown', 'error': f'Status code: {response.status_code}'}
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def get_result_details(self, request_id):
        """Get detailed processing results"""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/result/{request_id}",
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            return {'error': f'Status code: {response.status_code}'}
        except Exception as e:
            logger.error(f"Error getting result details: {e}")
            return {'error': str(e)}
    
    def get_health(self):
        """Get API Gateway health status"""
        try:
            response = requests.get(f"{self.base_url}/api/v1/health", timeout=10)
            if response.status_code == 200:
                return response.json()
            return {'status': 'unhealthy', 'error': f'Status code: {response.status_code}'}
        except Exception as e:
            logger.error(f"Error getting health: {e}")
            return {'status': 'error', 'error': str(e)}

api_client = APIGatewayClient(API_GATEWAY_URL)

@app.route('/')
def index():
    """Main page - adaptive based on device type"""
    # Get frontend configuration
    user_agent = request.headers.get('User-Agent', '')
    bandwidth = request.args.get('bandwidth')
    config = api_client.get_frontend_config(user_agent, bandwidth)
    
    # Get available services
    services_data = api_client.get_services()
    services = services_data.get('services', {})
    
    # Get system health
    health = api_client.get_health()
    
    template = ADAPTIVE_FRONTEND_TEMPLATE if config['ui_mode'] == 'desktop' else MOBILE_FRONTEND_TEMPLATE
    
    return render_template_string(
        template,
        config=config,
        services=services,
        health=health,
        api_gateway_url=API_GATEWAY_URL
    )

@app.route('/api/submit', methods=['POST'])
def submit_processing():
    """Submit image processing request via API Gateway"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No image file selected'}), 400
        
        service_name = request.form.get('service', 'grayscale')
        threads = int(request.form.get('threads', 4))
        runs = int(request.form.get('runs', 1))
        
        # Submit to API Gateway
        result = api_client.submit_processing_request(service_name, file, threads, runs)
        
        if 'error' in result:
            return jsonify(result), 500
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in submit_processing: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<request_id>')
def get_processing_status(request_id):
    """Get processing status from API Gateway"""
    result = api_client.get_status(request_id)
    return jsonify(result)

@app.route('/api/result/<request_id>')  
def get_processing_result(request_id):
    """Get detailed processing results from API Gateway"""
    result = api_client.get_result_details(request_id)
    return jsonify(result)

@app.route('/download/<request_id>')
def download_result(request_id):
    """Redirect to API Gateway download endpoint"""
    return redirect(f"{API_GATEWAY_URL}/api/v1/download/{request_id}")

@app.route('/health')
def health():
    """Frontend health check"""
    api_health = api_client.get_health()
    
    status = {
        'frontend': 'healthy',
        'api_gateway': api_health.get('status', 'unknown'),
        'timestamp': time.time()
    }
    
    return jsonify(status)

# Adaptive Frontend Templates

ADAPTIVE_FRONTEND_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenMP Image Processing - API Gateway</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container {
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            padding: 30px;
            margin: 20px 0;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        .header h1 {
            color: #333;
            margin-bottom: 10px;
        }
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
            margin: 0 5px;
        }
        .status-healthy { background: #d4edda; color: #155724; }
        .status-unhealthy { background: #f8d7da; color: #721c24; }
        .service-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .service-card {
            border: 2px solid #e9ecef;
            border-radius: 10px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .service-card:hover {
            border-color: #667eea;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .service-card.selected {
            border-color: #667eea;
            background: #f8f9ff;
        }
        .upload-area {
            border: 3px dashed #ccc;
            border-radius: 10px;
            padding: 40px;
            text-align: center;
            margin: 20px 0;
            transition: all 0.3s ease;
        }
        .upload-area.dragover {
            border-color: #667eea;
            background: #f8f9ff;
        }
        .controls {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .control-group {
            display: flex;
            flex-direction: column;
        }
        .control-group label {
            font-weight: bold;
            margin-bottom: 5px;
            color: #333;
        }
        .control-group input, .control-group select {
            padding: 10px;
            border: 2px solid #e9ecef;
            border-radius: 5px;
            font-size: 16px;
        }
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s ease;
            margin: 10px 5px;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
        }
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        .results {
            margin-top: 30px;
        }
        .result-item {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            margin: 15px 0;
            border-left: 4px solid #667eea;
        }
        .processing-status {
            display: inline-block;
            padding: 5px 10px;
            border-radius: 15px;
            font-size: 0.9em;
            font-weight: bold;
            margin-left: 10px;
        }
        .status-queued { background: #fff3cd; color: #856404; }
        .status-processing { background: #d1ecf1; color: #0c5460; }
        .status-completed { background: #d4edda; color: #155724; }
        .status-failed { background: #f8d7da; color: #721c24; }
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin: 15px 0;
        }
        .metric {
            background: white;
            padding: 10px;
            border-radius: 5px;
            text-align: center;
            border: 1px solid #e9ecef;
        }
        .metric-value {
            font-size: 1.2em;
            font-weight: bold;
            color: #667eea;
        }
        .metric-label {
            font-size: 0.8em;
            color: #666;
        }
        .queue-status {
            margin: 20px 0;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 10px;
        }
        #progressContainer {
            margin: 20px 0;
        }
        .progress-bar {
            width: 100%;
            height: 20px;
            background: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            width: 0%;
            transition: width 0.3s ease;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🖼️ OpenMP Image Processing</h1>
            <p>Powered by API Gateway Architecture</p>
            <div>
                <span class="status-badge status-{{ 'healthy' if health.status == 'healthy' else 'unhealthy' }}">
                    API Gateway: {{ health.status|title }}
                </span>
                {% for service_name, service_info in health.services.items() %}
                <span class="status-badge status-{{ 'healthy' if service_info.status == 'healthy' else 'unhealthy' }}">
                    {{ service_name|title }}: {{ service_info.status|title }}
                </span>
                {% endfor %}
            </div>
        </div>

        <!-- Service Selection -->
        <div class="service-grid">
            {% for service_name, service_info in services.items() %}
            <div class="service-card" data-service="{{ service_name }}">
                <h3>{{ service_name|title }} Service</h3>
                <p>{{ service_info.description }}</p>
                <div class="queue-status">
                    <strong>Queue Depth:</strong> {{ service_info.queue_depth }} pending
                </div>
            </div>
            {% endfor %}
        </div>

        <!-- Upload Area -->
        <div class="upload-area" id="uploadArea">
            <p>📁 Drop images here or click to select</p>
            <input type="file" id="imageInput" accept="image/*" multiple style="display: none;">
        </div>

        <!-- Processing Controls -->
        <div class="controls" id="controls" style="display: none;">
            <div class="control-group">
                <label for="threads">OpenMP Threads:</label>
                <select id="threads">
                    <option value="1">1 Thread</option>
                    <option value="2">2 Threads</option>
                    <option value="4" selected>4 Threads</option>
                    <option value="6">6 Threads</option>
                    <option value="8">8 Threads</option>
                </select>
            </div>
            <div class="control-group">
                <label for="runs">Number of Runs:</label>
                <select id="runs">
                    <option value="1" selected>1 Run</option>
                    <option value="3">3 Runs</option>
                    <option value="5">5 Runs</option>
                    <option value="10">10 Runs</option>
                </select>
            </div>
        </div>

        <div id="progressContainer" style="display: none;">
            <div class="progress-bar">
                <div class="progress-fill" id="progressBar"></div>
            </div>
            <p id="progressText">Processing...</p>
        </div>

        <button class="btn" id="processBtn" onclick="processImages()" disabled>
            🚀 Process Images
        </button>

        <!-- Results -->
        <div class="results" id="results"></div>
    </div>

    <script>
        let selectedFiles = [];
        let selectedService = 'grayscale';
        let processingResults = [];
        const pollingInterval = {{ config.polling_interval }};

        // Service selection
        document.querySelectorAll('.service-card').forEach(card => {
            card.addEventListener('click', function() {
                document.querySelectorAll('.service-card').forEach(c => c.classList.remove('selected'));
                this.classList.add('selected');
                selectedService = this.dataset.service;
            });
        });

        // Initialize first service as selected
        document.querySelector('.service-card').classList.add('selected');

        // File upload handling
        const uploadArea = document.getElementById('uploadArea');
        const imageInput = document.getElementById('imageInput');
        const controls = document.getElementById('controls');
        const processBtn = document.getElementById('processBtn');

        uploadArea.addEventListener('click', () => imageInput.click());
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            handleFiles(e.dataTransfer.files);
        });
        imageInput.addEventListener('change', (e) => {
            handleFiles(e.target.files);
        });

        function handleFiles(files) {
            selectedFiles = Array.from(files).filter(file => file.type.startsWith('image/'));
            if (selectedFiles.length > 0) {
                uploadArea.innerHTML = `<p>📁 ${selectedFiles.length} image(s) selected</p>`;
                controls.style.display = 'grid';
                processBtn.disabled = false;
            }
        }

        async function processImages() {
            if (selectedFiles.length === 0) return;

            processBtn.disabled = true;
            document.getElementById('progressContainer').style.display = 'block';
            
            const threads = document.getElementById('threads').value;
            const runs = document.getElementById('runs').value;
            
            processingResults = [];
            
            for (let i = 0; i < selectedFiles.length; i++) {
                const file = selectedFiles[i];
                const progress = ((i + 1) / selectedFiles.length) * 100;
                
                document.getElementById('progressBar').style.width = progress + '%';
                document.getElementById('progressText').textContent = 
                    `Processing ${file.name} (${i + 1}/${selectedFiles.length})`;
                
                try {
                    const formData = new FormData();
                    formData.append('image', file);
                    formData.append('service', selectedService);
                    formData.append('threads', threads);
                    formData.append('runs', runs);
                    
                    const response = await fetch('/api/submit', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (result.request_id) {
                        processingResults.push({
                            request_id: result.request_id,
                            filename: file.name,
                            service: selectedService,
                            status: 'queued',
                            threads: threads,
                            runs: runs
                        });
                        
                        // Start polling for this request
                        pollResult(result.request_id);
                    }
                } catch (error) {
                    console.error('Error processing', file.name, error);
                }
            }
            
            document.getElementById('progressContainer').style.display = 'none';
            processBtn.disabled = false;
            displayResults();
        }

        async function pollResult(requestId) {
            try {
                const response = await fetch(`/api/status/${requestId}`);
                const status = await response.json();
                
                // Update result in array
                const resultIndex = processingResults.findIndex(r => r.request_id === requestId);
                if (resultIndex !== -1) {
                    processingResults[resultIndex] = { ...processingResults[resultIndex], ...status };
                    displayResults();
                }
                
                // Continue polling if still processing
                if (status.status === 'processing' || status.status === 'queued') {
                    setTimeout(() => pollResult(requestId), pollingInterval);
                } else if (status.status === 'completed') {
                    // Get detailed results
                    const detailResponse = await fetch(`/api/result/${requestId}`);
                    const details = await detailResponse.json();
                    if (resultIndex !== -1) {
                        processingResults[resultIndex] = { ...processingResults[resultIndex], ...details };
                        displayResults();
                    }
                }
            } catch (error) {
                console.error('Error polling result for', requestId, error);
            }
        }

        function displayResults() {
            const resultsDiv = document.getElementById('results');
            
            if (processingResults.length === 0) {
                resultsDiv.innerHTML = '';
                return;
            }
            
            let html = '<h2>🎯 Processing Results</h2>';
            
            processingResults.forEach(result => {
                html += `
                    <div class="result-item">
                        <h3>${result.filename}
                            <span class="processing-status status-${result.status}">${result.status}</span>
                        </h3>
                        <p><strong>Service:</strong> ${result.service} | 
                           <strong>Threads:</strong> ${result.threads} | 
                           <strong>Runs:</strong> ${result.runs}</p>
                `;
                
                if (result.status === 'completed') {
                    html += `<a href="/download/${result.request_id}" class="btn">📥 Download Result</a>`;
                    
                    if (result.metrics) {
                        html += `
                            <div class="metrics">
                                <div class="metric">
                                    <div class="metric-value">${result.metrics.processing_time?.toFixed(3) || 'N/A'}s</div>
                                    <div class="metric-label">Processing Time</div>
                                </div>
                                <div class="metric">
                                    <div class="metric-value">${result.metrics.openmp_time?.toFixed(3) || 'N/A'}s</div>
                                    <div class="metric-label">OpenMP Time</div>
                                </div>
                                <div class="metric">
                                    <div class="metric-value">${result.metrics.efficiency?.toFixed(1) || 'N/A'}%</div>
                                    <div class="metric-label">Efficiency</div>
                                </div>
                            </div>
                        `;
                    }
                } else if (result.status === 'failed') {
                    html += `<p style="color: red;"><strong>Error:</strong> ${result.error || 'Unknown error'}</p>`;
                }
                
                html += '</div>';
            });
            
            resultsDiv.innerHTML = html;
        }

        // Auto-refresh page every 30 seconds to update service status
        setInterval(() => {
            if (processingResults.every(r => r.status === 'completed' || r.status === 'failed')) {
                location.reload();
            }
        }, 30000);
    </script>
</body>
</html>
'''

MOBILE_FRONTEND_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Image Processing</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 15px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .header {
            text-align: center;
            margin-bottom: 20px;
        }
        .upload-area {
            border: 2px dashed #ccc;
            border-radius: 8px;
            padding: 30px 15px;
            text-align: center;
            margin: 15px 0;
        }
        .btn {
            background: #007AFF;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 8px;
            font-size: 16px;
            width: 100%;
            margin: 10px 0;
        }
        .controls {
            margin: 15px 0;
        }
        .control-group {
            margin: 10px 0;
        }
        .control-group label {
            display: block;
            margin-bottom: 5px;
            font-weight: 600;
        }
        .control-group select {
            width: 100%;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 6px;
        }
        .result-item {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
        }
        .status-completed { color: #28a745; }
        .status-processing { color: #007bff; }
        .status-failed { color: #dc3545; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📱 Image Processing</h1>
            <p>Mobile Optimized</p>
        </div>

        <div class="upload-area" id="uploadArea">
            <p>📁 Tap to select image</p>
            <input type="file" id="imageInput" accept="image/*" style="display: none;">
        </div>

        <div class="controls" id="controls" style="display: none;">
            <div class="control-group">
                <label for="service">Service:</label>
                <select id="service">
                    {% for service_name in services.keys() %}
                    <option value="{{ service_name }}">{{ service_name|title }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="control-group">
                <label for="threads">Threads:</label>
                <select id="threads">
                    <option value="1">1</option>
                    <option value="2">2</option>
                    <option value="4" selected>4</option>
                </select>
            </div>
        </div>

        <button class="btn" id="processBtn" onclick="processImage()" disabled>
            🚀 Process Image
        </button>

        <div id="results"></div>
    </div>

    <script>
        let selectedFile = null;

        document.getElementById('uploadArea').addEventListener('click', () => {
            document.getElementById('imageInput').click();
        });

        document.getElementById('imageInput').addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                selectedFile = e.target.files[0];
                document.getElementById('uploadArea').innerHTML = `<p>📁 ${selectedFile.name}</p>`;
                document.getElementById('controls').style.display = 'block';
                document.getElementById('processBtn').disabled = false;
            }
        });

        async function processImage() {
            if (!selectedFile) return;

            const formData = new FormData();
            formData.append('image', selectedFile);
            formData.append('service', document.getElementById('service').value);
            formData.append('threads', document.getElementById('threads').value);
            formData.append('runs', '1');

            try {
                const response = await fetch('/api/submit', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();
                
                if (result.request_id) {
                    displayResult({
                        request_id: result.request_id,
                        filename: selectedFile.name,
                        status: 'processing'
                    });
                    pollResult(result.request_id);
                }
            } catch (error) {
                console.error('Error:', error);
            }
        }

        async function pollResult(requestId) {
            try {
                const response = await fetch(`/api/status/${requestId}`);
                const status = await response.json();
                
                displayResult({
                    request_id: requestId,
                    filename: selectedFile.name,
                    ...status
                });
                
                if (status.status === 'processing' || status.status === 'queued') {
                    setTimeout(() => pollResult(requestId), {{ config.polling_interval }});
                }
            } catch (error) {
                console.error('Error polling:', error);
            }
        }

        function displayResult(result) {
            const resultsDiv = document.getElementById('results');
            let html = `
                <div class="result-item">
                    <h3>${result.filename}</h3>
                    <p class="status-${result.status}">Status: ${result.status}</p>
            `;
            
            if (result.status === 'completed') {
                html += `<a href="/download/${result.request_id}" class="btn">📥 Download</a>`;
            }
            
            html += '</div>';
            resultsDiv.innerHTML = html;
        }
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
