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
