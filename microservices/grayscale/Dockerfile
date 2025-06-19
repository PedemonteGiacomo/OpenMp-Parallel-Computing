FROM ubuntu:22.04
RUN apt-get update && apt-get install -y build-essential python3 python3-pip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY c /app/c
WORKDIR /app/c
RUN make
WORKDIR /app
COPY app.py requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt
EXPOSE 5000
CMD ["python3", "app.py"]
