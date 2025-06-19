import os
import tempfile
import subprocess
from flask import Flask, request, send_file, abort

BINARY_PATH = os.path.join(os.path.dirname(__file__), 'bin', 'grayscale')
app = Flask(__name__)

@app.route('/grayscale', methods=['POST'])
def grayscale():
    if 'image' not in request.files:
        return 'missing image', 400
    img_file = request.files['image']
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, img_file.filename)
        out_path = os.path.join(tmpdir, 'out.png')
        img_file.save(in_path)
        result = subprocess.run([BINARY_PATH, in_path, out_path], capture_output=True)
        if result.returncode != 0:
            app.logger.error(result.stderr.decode())
            abort(500, 'processing failed')
        return send_file(out_path, mimetype='image/png')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
