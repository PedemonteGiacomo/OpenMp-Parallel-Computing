# Event-Driven Architecture with OpenMP Performance Testing

This system demonstrates a microservices-based event-driven architecture using RabbitMQ and MinIO for image processing with OpenMP. The system includes tools for load testing, benchmarking, and visualizing OpenMP parallel performance.

## Table of Contents
1. [Components](#components)
2. [Setting Up](#setting-up)
3. [Running Tests](#running-tests)
   - [Basic Testing](#basic-testing)
   - [Load Testing](#load-testing) 
   - [Benchmark Testing](#benchmark-testing)
   - [Safe Benchmark Mode](#safe-benchmark-mode)
4. [Monitoring and Managing](#monitoring-and-managing)
   - [RabbitMQ Monitoring](#rabbitmq-monitoring)
   - [Service Recovery](#service-recovery)
5. [Understanding Results](#understanding-results)
   - [OpenMP Performance Metrics](#openmp-performance-metrics)
   - [Visualizing Results](#visualizing-results)
   - [Prometheus Metrics](#prometheus-metrics)
6. [Advanced Usage](#advanced-usage)
   - [Tuning for Scale](#tuning-for-scale)
   - [Adding Custom Tests](#adding-custom-tests)
7. [Troubleshooting](#troubleshooting)
8. [Adding New Processing Services](#adding-new-processing-services)
9. [Educational Use and Learning OpenMP](#educational-use-and-learning-openmp)

## Components

- **MinIO** – Local object storage for uploaded and processed images
- **RabbitMQ** – Message queue for decoupling services
- **grayscale_service** – Worker that performs the grayscale conversion using OpenMP
- **frontend** – Flask application for submitting images, viewing results, and displaying processing errors
- **Testing Tools** – Scripts for load testing, benchmarking, and monitoring

## Setting Up

1. **Build and start the stack**

   ```bash
   cd event-driven
   docker compose up --build
   ```

2. **Create a Python virtual environment** (recommended)

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r scripts/requirements.txt
   ```

3. **Verify services are running**

   Check that all services are healthy:
   ```bash
   docker compose ps
   ```

   Test with a single image:
   ```bash
   python3 scripts/load_test.py images/test.jpg
   ```

## Running Tests

### Basic Testing

The simplest way to test the system is through the web UI:

1. Open `http://localhost:8080` in your browser
2. Upload an image
3. Select thread counts (1, 2, 4, 6) and number of runs
4. Submit and observe the processing time charts

### Load Testing

The `load_test.py` script allows you to submit multiple requests with configurable concurrency:

```bash
python3 scripts/load_test.py images/test.jpg --count 10 --concurrency 4 --delay 1.0
```

Parameters:
- `--count`: Number of image processing requests to send
- `--concurrency`: Number of concurrent workers
- `--delay`: Delay between requests in seconds (prevents overloading)
- `--timeout`: Maximum time to wait for processing (default: 60s)
- `--retries`: Number of retry attempts if a request fails (default: 3)
- `--debug`: Print detailed debug information

Example for testing different image sizes:
```bash
# Test with a small image
python3 scripts/load_test.py images/test.jpg --count 5 --concurrency 2

# Test with a larger image
python3 scripts/load_test.py images/more_than_one_mega_photo.jpg --count 5 --concurrency 2
```

### Benchmark Testing

For comprehensive performance testing across different request volumes:

```bash
python3 scripts/benchmark_plot.py images/test.jpg --counts "1,5,10,20" --concurrency 4
```

Parameters:
- `--counts`: Comma-separated list of request counts to test
- `--concurrency`: Maximum number of concurrent requests
- `--output`: Filename for the output graph (default: benchmark.png)
- `--safer`: Use more conservative settings to prevent overloading

Example for focused OpenMP thread scaling test:
```bash
# Test with small batches but multiple thread combinations
python3 scripts/benchmark_plot.py images/test.jpg --counts "1,3,5" --safer
```

> **Note on Concurrency Limits**: By default, the script caps the actual concurrency at 5 for requests ≤20 and at 3 for larger request counts, regardless of the `--concurrency` value you provide. This is a safety feature to prevent overloading the system.

#### Using Full Concurrency Levels

For advanced testing cases where you want to use the exact concurrency level you specify (at your own risk), use the uncapped version:

```bash
# Run with exactly 10 concurrent requests (may overload the system)
python3 scripts/benchmark_plot_uncapped.py images/test.jpg --counts "1,10,20" --concurrency 10 --force-concurrency
```

The uncapped version adds this parameter:
- `--force-concurrency`: Force using the exact concurrency level specified (may overload RabbitMQ)

#### Come Funziona la Concorrenza nel Sistema

La concorrenza nel sistema opera a diversi livelli e il parametro `--force-concurrency` influisce direttamente sul comportamento del carico di lavoro:

**Flusso di una richiesta concorrente:**

1. **Livello Client (script di benchmark):**
   - Il parametro `--concurrency N` crea un pool di N worker
   - Ogni worker invia una richiesta HTTP al frontend
   - Non appena un worker completa una richiesta, ne invia immediatamente un'altra (fino al raggiungimento di `--count` totale)

2. **Livello Frontend:**
   - Riceve le richieste HTTP dai client
   - Salva l'immagine su MinIO
   - Pubblica un messaggio su RabbitMQ con il riferimento all'immagine
   - Risponde al client con un ID per tracciare lo stato

3. **Livello RabbitMQ:**
   - Le richieste si accumulano in coda se arrivano più velocemente di quanto possano essere elaborate
   - La coda funziona come buffer tra frontend e worker

4. **Livello Worker (grayscale_service):**
   - Preleva messaggi dalla coda in base al parametro `prefetch_count` (default: 1)
   - Per ogni messaggio:
     - Avvia un thread per elaborare l'immagine con OpenMP
     - Il codice OpenMP utilizza internamente `N` thread (parametro specificato nella richiesta)
     - Salva l'immagine elaborata su MinIO
     - Notifica il frontend del completamento

**Cosa significa `--force-concurrency`:**

Quando usi `benchmark_plot_uncapped.py` con `--force-concurrency`:

1. **Bypass del limitatore di sicurezza** - Lo script non applica più i limiti di sicurezza che normalmente riducono la concorrenza (5 per richieste ≤20, 3 per richieste maggiori)
2. **Invio effettivo di N richieste simultanee** - Esattamente N client invieranno richieste HTTP al frontend contemporaneamente
3. **Saturazione potenziale del sistema** - RabbitMQ può accumulare un backlog significativo se il grayscale_service non processa abbastanza velocemente

**Il comportamento del grayscale_service:**

- **Elaborazione sequenziale o parallela** - Il service elabora una richiesta alla volta per default (`prefetch_count=1`)
- **Elaborazione con prefetch** - Se `prefetch_count` > 1, il service può elaborare più messaggi contemporaneamente
- **Ogni richiesta usa OpenMP** - Indipendentemente dal `prefetch_count`, ogni singola elaborazione di immagine sfrutta OpenMP con il numero di thread specificato

**Esempio concreto:**
```
python3 scripts/benchmark_plot_uncapped.py images/test.jpg --counts "1,10,20" --concurrency 10 --force-concurrency
```

In questo esempio:
- 10 client simultanei inviano richieste HTTP al frontend
- Il frontend pubblica 10 messaggi su RabbitMQ quasi istantaneamente
- Se grayscale_service ha `prefetch_count=1`, elaborerà una richiesta alla volta (ma utilizzerà OpenMP per ogni richiesta)
- Se grayscale_service ha `prefetch_count=2`, elaborerà 2 richieste in parallelo (ciascuna con OpenMP)
- Ogni elaborazione OpenMP utilizzerà internamente i thread specificati nella richiesta (1, 2, 4, 6)

**Quando utilizzare `--force-concurrency`:**
- Test di stress del sistema
- Simulazione di carichi di picco
- Valutazione del comportamento sotto carico elevato
- Determinazione della capacità massima del sistema

**Rischi dell'uso di `--force-concurrency`:**
- Sovraccarico di RabbitMQ
- Esaurimento della memoria
- Timeout delle richieste
- Crash dei servizi

### Safe Benchmark Mode

To avoid overwhelming RabbitMQ during benchmarking, use the safe benchmark script:

```bash
./scripts/safe_benchmark.sh
```

This script runs benchmarks with conservative parameters that prevent RabbitMQ from being overloaded.

## Monitoring and Managing

### RabbitMQ Monitoring

Monitor RabbitMQ queue status during testing:

```bash
# Check queue status
python3 scripts/manage_rabbitmq.py status

# Monitor queues continuously
python3 scripts/manage_rabbitmq.py monitor

# Purge queues when they get overloaded
python3 scripts/manage_rabbitmq.py purge
```

### Service Recovery

If services crash or RabbitMQ becomes overloaded, use the recovery script:

```bash
./scripts/reset_services.sh
```

This interactive script provides options to:
- Check service status
- Purge RabbitMQ queues
- Restart individual services
- Perform an ordered restart of the entire system
- Monitor RabbitMQ queues

## Understanding Results

### OpenMP Performance Metrics

The system provides several ways to measure OpenMP performance:

1. **Frontend Charts**: The web UI displays two charts:
   - Execution time for each thread count
   - Speed-up factor relative to single-thread performance

2. **Process Time Metrics**: The grayscale service records processing time in Prometheus:
   - `grayscale_process_seconds`: Time spent executing the OpenMP algorithm
   - Accessible at `http://localhost:8001/`

3. **Benchmark Reports**: The benchmark script generates plots showing:
   - Average latency by request count
   - 95th percentile latency
   - Throughput (requests/second)
   - Success rate

Example of extracting raw OpenMP timing data:
```bash
# Run a single request and extract timing data
curl -s http://localhost:8001/ | grep "grayscale_process_seconds"
```

### Visualizing Results

Benchmark plots (generated at `benchmark.png` or `benchmark_safe.png`) contain four panels:

1. **Average Latency**: Total request processing time as request count increases
2. **95th Percentile Latency**: Worst-case performance indicator
3. **Throughput**: Requests per second the system can handle
4. **Prometheus Averages**: Breakdown of time spent in queue, processing, and total

These visualizations help identify:
- OpenMP scaling efficiency across thread counts
- System bottlenecks as load increases
- Queue saturation points

### Prometheus Metrics

Available metrics endpoints:

- **Frontend**: `http://localhost:8000/metrics`
  - `frontend_request_seconds`: Time from upload to completed processing
  - `frontend_publish_total`: Total messages published to the queue
  - `frontend_processed_total`: Total processed notifications received

- **Worker**: `http://localhost:8001/`
  - `grayscale_queue_wait_seconds`: Time messages spend waiting in the queue
  - `grayscale_process_seconds`: Time spent executing the OpenMP algorithm
  - `grayscale_startup_seconds`: Time from container start to first processed message
  - `grayscale_failures_total`: Number of processing failures
  - `grayscale_reconnect_attempts`: Connection retry attempts to RabbitMQ

## Advanced Usage

### Tuning for Scale

Adjust these parameters for handling larger workloads:

1. **RabbitMQ Prefetch Count**: Controls how many messages the worker processes simultaneously
   ```bash
   # Start container with custom prefetch count
   PREFETCH_COUNT=2 docker compose up grayscale_service
   ```

2. **Thread Allocation**: Balance between parallelism and resource contention
   ```bash
   # Test different thread combinations
   python3 scripts/load_test.py images/test.jpg --count 5 --concurrency 2
   ```

3. **Batch Size**: Adjust request counts based on image size
   ```bash
   # For larger images, use smaller batches
   python3 scripts/benchmark_plot.py images/more_than_one_mega_photo.jpg --counts "1,3,5"
   ```

### Adding Custom Tests

Create custom test scenarios by combining available tools:

```bash
# Example: Test recovery from queue saturation
./scripts/reset_services.sh  # Start with clean services
python3 scripts/benchmark_plot.py images/test.jpg --counts "1,20,50" # Run intensive benchmark
./scripts/reset_services.sh  # Recover system
python3 scripts/manage_rabbitmq.py monitor # Check queue health
```

## Troubleshooting

Common issues and solutions:

1. **RabbitMQ Overload**
   - Symptoms: 500 errors, connection refusals, workers crashing
   - Solution: Run `./scripts/reset_services.sh` and select "Purge RabbitMQ queues"

2. **Service Crashes**
   - Symptoms: Services become unresponsive
   - Solution: Use ordered restart option in `reset_services.sh`

3. **Benchmark Failures**
   - Symptoms: Incomplete plots, missing data points
   - Solution: Use `--safer` flag or reduce concurrency and counts

4. **Frontend Issues**
   - Symptoms: JavaScript errors like "Error Polling Assignment to constant variable", "Error Polling: error to fetch"
   - Solution: The frontend has been restored to a simpler, more reliable implementation without the advanced polling counter. If issues persist, rebuild the frontend container:
     ```bash
     cd /path/to/event-driven
     docker-compose build frontend
     docker-compose up -d frontend
     ```
   - Note: A backup of the previous complex frontend implementation is available as `frontend/app.py.complex`

5. **Connection Issues Between Services**
   - Symptoms: "Connection refused" errors in service logs, particularly at startup
   - Solution: Services now have improved retry logic, but it's best to start them in the correct order:
     ```bash
     # Start infrastructure first
     docker-compose up -d minio rabbitmq
     sleep 5  # Wait for services to initialize
     
     # Start backend service
     docker-compose up -d grayscale_service
     sleep 3  # Wait for backend to initialize
     
     # Start frontend last
     docker-compose up -d frontend
     ```
   - If problems persist, use the reset_services.sh script

6. **Processing Errors**
   - Symptoms: Frontend displays "Error: [error message]" instead of processed image
   - Solution: The system now has error reporting between services. When the grayscale service encounters an error during processing, it sends an error message via RabbitMQ, which is displayed in the frontend.
   - Check logs with `docker-compose logs grayscale_service` to see detailed error information

7. **RabbitMQ Missed Heartbeats and Connection Issues**
   - Symptoms: 
     - Error message `missed heartbeats from client, timeout: 180s`
     - Error message `pop from an empty deque` in Pika
     - Connection drops between services and RabbitMQ
     - `'NoneType' object has no attribute` errors
   - Solution: The system now implements robust heartbeat and connection handling:
     ```
     1. Reduced heartbeat interval from 180s to 30s
     2. Added background heartbeat thread that processes events every 15s with timeout protection
     3. Implemented automatic reconnection with exponential backoff
     4. Enhanced error handling in both frontend and backend services
     5. Added TCP optimizations (TCP_NODELAY, keepalive, etc.)
     6. Implemented better connection lifecycle management
     7. Added container auto-restart policies
     ```
   - If issues persist, you can manually increase the heartbeat frequency or restart the services:
     ```bash
     # Restart the services in the correct order
     docker-compose down
     docker-compose up -d rabbitmq minio
     sleep 5
     docker-compose up -d grayscale_service
     sleep 3
     docker-compose up -d frontend
     ```

## Adding New Processing Services

To add a new OpenMP-based processing service:

1. **Create a new folder** under `event-driven/` (for example `blur_service`)
2. **Define queues** for the service in its app.py
3. **Update docker-compose.yml** to include the new service
4. **Extend the frontend** to offer the new processing option

For detailed instructions, see the "Adding a new processing service" section in the original documentation.

#### 9. Educational Use and Learning OpenMP

This system serves as an excellent educational tool for understanding parallel computing concepts and OpenMP programming. Here are some suggested learning exercises:

**9.1 OpenMP Scaling Law Experiments**

Run experiments to verify Amdahl's Law, which predicts theoretical speedup in parallel systems:

```bash
# Run tests with increasing thread counts
python3 scripts/extract_openmp_metrics.py --mode test --threads 1,2,4,8,16,32 --repeats 3

# Plot the results and compare to the theoretical formula:
# Speedup(N) = 1 / (s + p/N) where:
# - N is the number of threads
# - s is the serial fraction of the code
# - p is the parallel fraction (1-s)
```

**9.2 Exploring Thread Affinity**

Experiment with different thread affinity settings to understand their impact:

```bash
# Test with different affinity settings (requires modifying the Docker setup)
OMP_PROC_BIND=close docker compose up -d grayscale_service
# Then run your benchmark
python3 scripts/benchmark_plot.py images/test.jpg --counts "1,5,10"

# Change to a different setting
docker compose down
OMP_PROC_BIND=spread docker compose up -d grayscale_service
# Re-run benchmark and compare results
```

**9.3 Analyzing OpenMP Overhead**

Measure the overhead introduced by OpenMP parallelization:

```bash
# Use very small images where parallel overhead might exceed benefits
python3 scripts/extract_openmp_metrics.py --mode test --image images/test.jpg --threads 1,2,4,8 --repeats 10
```

**9.4 Modifying the Parallel Implementation**

For a deeper understanding, you can modify the OpenMP implementation in `grayscale_service/c/src/parallel_to_grayscale.c`:

1. Try different scheduling strategies:
   - `#pragma omp parallel for schedule(static)`
   - `#pragma omp parallel for schedule(dynamic)`
   - `#pragma omp parallel for schedule(guided)`

2. Experiment with different chunk sizes:
   - `#pragma omp parallel for schedule(static, 100)`
   - `#pragma omp parallel for schedule(dynamic, 50)`

3. Compare performance and learn which strategies work best for different image sizes

**9.5 Creating Your Own Performance Analysis Scripts**

Use this project as a template to create your own analysis tools:

```bash
# Clone and modify the extract_openmp_metrics.py script
cp scripts/extract_openmp_metrics.py scripts/my_custom_analysis.py

# Modify to add your own metrics or visualization techniques
# Then run your custom analysis
python3 scripts/my_custom_analysis.py --mode test
```

By working through these educational exercises, you'll gain practical experience with parallel computing concepts, OpenMP programming, and performance analysis of concurrent systems.

### Approfondimento Tecnico sul Funzionamento della Concorrenza

Il sistema implementa un modello di concorrenza a più livelli che è importante comprendere per ottimizzare correttamente i test:

#### Livelli di Concorrenza nel Sistema

1. **Concorrenza Client-Side**
   ```python
   # Nel file benchmark_plot_uncapped.py
   with concurrent.futures.ThreadPoolExecutor(max_workers=actual_concurrency) as ex:
       futures = []
       for i in range(count):
           futures.append(ex.submit(submit, image, url, ...))
   ```
   Questo codice crea un pool di thread che inviano richieste HTTP contemporaneamente. Il parametro `--concurrency` controlla direttamente la dimensione di questo pool.

2. **Controllo Concorrenza con `--force-concurrency`**
   ```python
   # Nel file benchmark_plot_uncapped.py
   if force_full_concurrency:
       actual_concurrency = concurrency
       print("Warning: Using full requested concurrency...")
   else:
       actual_concurrency = min(concurrency, 5 if count <= 20 else 3)
   ```
   Senza `--force-concurrency`, il sistema limita automaticamente la concorrenza per proteggere RabbitMQ.

3. **Prefetch Count nel Worker**
   ```python
   # Nel file grayscale_service/app.py
   PREFETCH_COUNT = int(os.environ.get('PREFETCH_COUNT', 1))
   # ...
   channel.basic_qos(prefetch_count=PREFETCH_COUNT)
   ```
   Questo parametro determina quanti messaggi il servizio può prelevare dalla coda contemporaneamente. Con un valore predefinito di 1, il service elabora un'immagine alla volta.

#### Diagramma di Flusso della Concorrenza

```
Client 1 ─┐
Client 2 ─┼─→ Frontend ─→ RabbitMQ ─┬─→ Worker (prefetch=1) ───→ Thread OpenMP (N threads)
Client 3 ─┘                         │
                                   └─→ Worker (se prefetch>1) ─→ Thread OpenMP (N threads)
```

#### Comportamento di `benchmark_plot_uncapped.py`

Quando esegui:
```bash
python3 scripts/benchmark_plot_uncapped.py images/test.jpg --counts "1,10,20" --concurrency 10 --force-concurrency
```

Accade quanto segue:

1. Lo script crea esattamente 10 worker thread che inviano richieste HTTP simultanee
2. Ogni richiesta viene processata dal frontend e aggiunta alla coda RabbitMQ
3. Il grayscale_service preleva messaggi dalla coda in base al prefetch_count:
   - Se `PREFETCH_COUNT=1` (default): processa un'immagine alla volta
   - Se `PREFETCH_COUNT=3`: può processare 3 immagini contemporaneamente

4. Per ogni immagine, viene avviato un processo C/OpenMP che utilizza N thread specificati nella richiesta

#### Differenza tra Capped e Uncapped

Lo script originale `benchmark_plot.py` implementa una protezione:
```python
actual_concurrency = min(concurrency, 5 if count <= 20 else 3)
```

Questo significa che con `--concurrency 10`:
- Per richieste ≤20: userebbe al massimo 5 thread concorrenti 
- Per richieste >20: userebbe al massimo 3 thread concorrenti

La versione `benchmark_plot_uncapped.py` con `--force-concurrency` consente di bypassare questa limitazione e utilizzare il valore esatto specificato (10 nell'esempio).

#### Implicazioni Prestazionali

1. **Prefetch=1, Concurrency=10**: 
   - 10 client simultanei inviano richieste
   - Il worker elabora una richiesta alla volta
   - 9 richieste rimangono in attesa nella coda RabbitMQ
   - Ogni richiesta sfrutta OpenMP con parallelismo interno

2. **Prefetch=3, Concurrency=10**:
   - Il worker può elaborare 3 richieste in parallelo
   - Ogni richiesta avvia un processo separato con OpenMP
   - Si ha parallelismo sia a livello di richieste che a livello di elaborazione immagini
   - Maggiore utilizzo della CPU ma anche maggiore contention

#### Monitoraggio del Carico

Durante i test con concorrenza elevata, il sistema implementa controlli di sicurezza:
```python
rabbit_healthy, msg = check_rabbitmq_health()
if not rabbit_healthy:
    print(f"RabbitMQ appears overloaded. Pausing for recovery...")
    time.sleep(10)
```

Questi controlli verificano lo stato della coda e applicano backoff quando necessario per prevenire il collasso del sistema.

### Incremento della Complessità Computazionale

Per testare le prestazioni di OpenMP con carichi di lavoro più pesanti, è possibile utilizzare il parametro `--passes` che aumenta il numero di passate che l'algoritmo esegue sull'immagine:

```bash
# Esegue un test con 5 passate del kernel (5 volte più intensivo)
python3 scripts/load_test.py images/test.jpg --passes 5 --threads "1,2,4,6"

# Benchmark con carico computazionale aumentato
python3 scripts/benchmark_plot.py images/test.jpg --counts "1,5,10" --passes 3
```

Il parametro `--passes` è disponibile in tutti gli script di test:

- `load_test.py`: `--passes N` per aumentare la complessità di una singola richiesta
- `benchmark_plot.py`: `--passes N` per eseguire benchmark con elaborazione intensificata
- `extract_openmp_metrics.py`: `--passes N` per test di scalabilità più significativi
- `safe_benchmark.sh`: Accetta il numero di passate come primo argomento (`./safe_benchmark.sh 3`)

Aumentare il numero di passate del kernel:

1. Rende più evidente la differenza di prestazioni tra diverse configurazioni di thread
2. Fornisce dati più precisi sui benefici della parallelizzazione 
3. Permette di simulare algoritmi più complessi su immagini di piccole dimensioni
4. È ideale per test educativi sulla parallelizzazione

Il numero di passate è limitato a un massimo di 10 nell'interfaccia web per evitare sovraccarichi.

### Logging Avanzato

I log del servizio grayscale_service sono stati migliorati per fornire informazioni più dettagliate sull'elaborazione:

```
[2025-06-26 15:32:47] [REQUEST a89f3d21] Processing image uploads/test.jpg - threads=[4], passes=3, repeats=1, active_consumers=1, queue_depth=2
[2025-06-26 15:32:47] Running bin/grayscale temp/test.jpg output.png 3 (thread=4, run 1/1, passes=3, system=CPU: 78%, MEM: 65%)
[2025-06-26 15:32:48] Thread 4, run 1/1 - Kernel time: 0.1243s, total time: 0.1543s, passes=3, image_size=800x600 (0.48MP), throughput=3.86MP/s
```

Queste informazioni avanzate includono:

1. **Dettagli della richiesta**:
   - ID univoco della richiesta
   - Numero di thread OpenMP
   - Numero di passate del kernel
   - Numero di ripetizioni
   - Prefetch attivo nel worker
   - Stima della profondità della coda

2. **Dettagli dell'esecuzione**:
   - Utilizzo CPU e memoria del sistema
   - Parametri esatti dell'esecuzione
   - Informazioni sull'ambiente

3. **Metriche di prestazione**:
   - Tempo del kernel vs tempo totale
   - Dimensione dell'immagine elaborata
   - Throughput in megapixel al secondo
   - Statistiche separate per ogni configurazione di thread

Questi log dettagliati semplificano il debug, l'ottimizzazione e l'analisi delle prestazioni del sistema.
