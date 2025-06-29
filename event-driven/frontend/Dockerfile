FROM python:3
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY static ./static
EXPOSE 5000
CMD ["python", "app.py"]
