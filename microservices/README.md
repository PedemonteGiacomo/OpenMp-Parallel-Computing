# Microservices Structure

This directory contains a microservice-based approach for the image processing algorithms.  Each service exposes its functionality over HTTP and can be deployed as a standalone container.

Currently only the **grayscale** service is implemented.  It reuses the OpenMP implementation from the monolithic version.

```
microservices/
  grayscale/
    app.py            # Flask application exposing /grayscale
    requirements.txt  # Python dependencies
    Dockerfile        # container image
    c/
      src/*.c         # OpenMP implementation
      include/*.h
      Makefile        # builds bin/grayscale
```

Run the service locally with Docker:

```bash
cd microservices/grayscale
docker build -t grayscale-service .
docker run --rm -p 5000:5000 grayscale-service
```

Then POST an image to `http://localhost:5000/grayscale` with multipart form data using the field `image` and the service will return the processed PNG.
You can test this easily with the helper script `grayscale/test_client.py`:

```bash
python3 microservices/grayscale/test_client.py path/to/image.jpg output.png
```

The complete process (with all the dependencies to test the microservice with a test_client):

```bash
cd microservices/grayscale
python3 -m venv .venv
source .venv/bin/activate
pip install -r client_requirements.txt
cd ../..
python3 microservices/grayscale/test_client.py images/more_than_one_mega_photo.jpg output.png
```

The client requires the `requests` library (`pip install requests`).

The script measures the request time and saves the processed image. Optional parameters
`--threads=N` and `--passes=N` allow tweaking the OpenMP runtime and the number of kernel
passes. These values are forwarded to the service which then invokes the underlying binary
accordingly.
