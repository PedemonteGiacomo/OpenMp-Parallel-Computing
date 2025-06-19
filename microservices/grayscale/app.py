import os
import tempfile
import subprocess
import time
from flask import Flask, request, send_file, abort

BINARY_PATH = os.path.join(os.path.dirname(__file__), 'bin', 'grayscale')
app = Flask(__name__)

@app.route('/grayscale', methods=['POST'])
def grayscale():
    if 'image' not in request.files:
        return 'missing image', 400

    img_file = request.files['image']
    passes = request.form.get('passes')
    threads = request.form.get('threads')

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, img_file.filename)
        out_path = os.path.join(tmpdir, 'out.png')
        img_file.save(in_path)

        cmd = [BINARY_PATH, in_path, out_path]
        if passes:
            cmd.append(passes)

        env = os.environ.copy()
        if threads:
            env['OMP_NUM_THREADS'] = threads

        start = time.time()
        result = subprocess.run(cmd, capture_output=True, env=env)
        duration = time.time() - start

        if result.returncode != 0:
            app.logger.error(result.stderr.decode())
            abort(500, 'processing failed')

        response = send_file(out_path, mimetype='image/png')
        response.headers['X-Elapsed'] = f'{duration:.4f}'
        return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
