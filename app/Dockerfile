FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN opentelemetry-bootstrap -a install
COPY simulation.py topology.py main.py loadgen.py \
     store_topology.py store_main.py store_loadgen.py ./
# Exporter/Endpoint werden ueber OTEL_* Environment-Variablen in docker-compose.yml gesetzt.
CMD ["opentelemetry-instrument", \
     "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
