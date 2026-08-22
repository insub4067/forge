FROM python:3.12-slim

RUN useradd -m -u 1000 sandbox && \
    apt-get update && apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

USER sandbox
WORKDIR /workspace
