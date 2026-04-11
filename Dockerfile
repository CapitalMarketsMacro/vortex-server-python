FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake build-essential libssl-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY vortex/ ./vortex/

EXPOSE 8080

CMD ["vortex-server"]
