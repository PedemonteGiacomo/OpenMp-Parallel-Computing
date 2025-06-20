# Event Driven Example

This folder contains a minimal example of using an event driven architecture with
RabbitMQ and MinIO.  A frontend service publishes image processing jobs on a
message queue.  The `grayscale_service` subscribes to these events, downloads the
referenced image from object storage, converts it to grayscale using the same
OpenMP implementation as the standalone `microservices/grayscale` service and
uploads the result under a `processed/` prefix.  When running the full stack a user can
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

Below the images a small chart shows the processing time reported by the worker.
You can tweak the number of OpenMP threads and the number of kernel passes using
the form fields before uploading. Each completed job adds a bar to the graph so
it's easy to benchmark different configurations.

The setup is intentionally simple to demonstrate how a client can be completely
decoupled from a processing microservice by only exchanging messages through the
queue and storing payloads in object storage.

## Architecture overview

```
frontend  --publish-->  RabbitMQ  --consume-->  processing service
    |                                              |
    |  <-------download/upload images---------->   MinIO
```

The frontend never calls a microservice directly. It only sends a short message
on the queue containing the key of the uploaded image. Each worker listens on
its own queue, performs the OpenMP optimized algorithm and writes the result
back to MinIO. A second message notifies the frontend that processing completed.

## Adding a new processing service

1. **Create a new folder** under `event-driven/` (for example `blur_service`).
   Structure it like the existing `grayscale_service` with a `Dockerfile`, an
   `app.py` consumer and a `c/` directory containing the OpenMP program and
   `Makefile` to build it.
2. **Define queues.** Each service should consume from its own queue (e.g.
   `blur`) and publish results to a `<name>_processed` queue. Declare these
   queues in the worker similar to `grayscale_service/app.py`.
3. **Update `docker-compose.yml`** by adding a new service entry that builds
   the new folder. Make it depend on RabbitMQ and MinIO and pass the same
   environment variables.
4. **Extend the frontend.** Add a new action (button or menu) that lets the user
   choose which processing to trigger. Publish a message to the corresponding
   queue and listen for completion events (see the `consume_processed` function
   for an example). When a completion message arrives, display the processed
   image next to the original.

### Example: adding a blur microservice

As an example, to add a Gaussian blur processor:

1. Copy `grayscale_service` into `blur_service` and replace the C code with your
   OpenMP blur implementation. Adjust the `Makefile` so it builds a `blur`
   executable.
2. Edit `blur_service/app.py` so it consumes from the `blur` queue and publishes
   to `blur_processed` after uploading the result under `processed/`.
3. Add the following to `docker-compose.yml`:

   ```yaml
   blur_service:
     build: ./blur_service
     environment:
       MINIO_ENDPOINT: minio:9000
       MINIO_ACCESS_KEY: minioadmin
       MINIO_SECRET_KEY: minioadmin
       RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672/
     depends_on:
       - rabbitmq
       - minio
   ```

4. Update the frontend to allow selecting "Blur" and publish messages to the
   new queue. Start a consumer thread that listens on `blur_processed` and show
   the resulting image once available.

Following these steps you can add any number of additional algorithms, each in
its own container and queue, while the frontend remains loosely coupled and only
reacts to completion messages.
