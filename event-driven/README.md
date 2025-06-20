# Event Driven Example

This folder contains a minimal example of using an event driven architecture with
RabbitMQ and MinIO.  A frontend service publishes image processing jobs on a
message queue.  The `grayscale_service` subscribes to these events, downloads the
referenced image from object storage, converts it to grayscale and uploads the
result under a `processed/` prefix.  When running the full stack a user can
upload an image via the frontend and later retrieve the processed image.

## Components

- **MinIO** – local object storage used to store uploaded and processed images
- **RabbitMQ** – message bus used to decouple services
- **grayscale_service** – worker that performs the grayscale conversion
- **frontend** – simple Flask application to submit new images and view results

## Running locally

The included `docker-compose.yml` spins up all services.  Ensure Docker is
installed then run:

```bash
cd event-driven
docker compose up --build
```

The frontend will be available on http://localhost:8080. Upload an image and the
page will show the original and processed result on the same screen. It polls
automatically until the conversion finishes so no manual refresh is needed.

The setup is intentionally simple to demonstrate how a client can be completely
decoupled from a processing microservice by only exchanging messages through the
queue and storing payloads in object storage.
