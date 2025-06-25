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

1. Build and start the stack

   ```bash
   cd event-driven
   docker compose up --build
   ```

2. Open <http://localhost:8080> and upload an image. The page shows both the
   original and processed version and automatically refreshes until the job
   completes.

Below the images two charts summarize performance. Before uploading you can pick
one or more thread counts (1, 2, 4 or 6), the number of kernel passes and how
many times each configuration should run. The worker executes the OpenMP kernel
with every selected thread count, averaging the specified number of runs. The
frontend keeps your choices on screen after submission and plots both the
execution time and the resulting speed‑up for each thread count. Each chart is
rendered inside a fixed-size container so that interacting (e.g. zooming or
toggling datasets) does not collapse or shrink the canvas.

The setup is intentionally simple to demonstrate how a client can be completely
decoupled from a processing microservice by only exchanging messages through the
queue and storing payloads in object storage.

## Metrics

Both the frontend and the worker expose Prometheus metrics. When the stack is
running you can scrape:

- <http://localhost:8000/metrics> for frontend timings
- <http://localhost:8001/> for worker metrics

The metrics record queue wait time, processing duration and overall request
latency so you can compare local runs with cloud deployments.

## Load testing

The `scripts/load_test.py` helper submits many images to the frontend and waits
for the processed results. It measures latency for each request and prints a
summary table.

```
python3 scripts/load_test.py images/test.jpg --count 100 --concurrency 10
```

To run the same test across multiple request counts and automatically
generate latency graphs install `matplotlib` and use
`scripts/benchmark_plot.py`:

```bash
pip install requests matplotlib --user
python3 scripts/benchmark_plot.py images/test.jpg
```

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
