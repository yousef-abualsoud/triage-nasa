# Multi-stage build: C++ solver → Python backend → frontend bundle.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# ---------- Stage 1: C++ solver (pybind11 module) ----------
FROM base AS cpp-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build git \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pybind11
WORKDIR /solver
COPY CMakeLists.txt ./
COPY src/cpp/ ./src/cpp/
RUN cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -Dpybind11_DIR="$(python -m pybind11 --cmakedir)" \
 && cmake --build build -j \
 && mv build/triage_core*.so /usr/local/lib/

# ---------- Stage 2: Python backend deps ----------
FROM base AS backend
RUN pip install --no-cache-dir \
    numpy pydantic boto3 botocore websockets httpx openai

COPY --from=cpp-builder /usr/local/lib/triage_core*.so /usr/local/lib/
ENV LD_LIBRARY_PATH=/usr/local/lib
ENV PYTHONPATH=/usr/local/lib

COPY src/shared/ /app/src/shared/
COPY src/python/ /app/src/python/
WORKDIR /app

# ---------- Stage 3: Frontend bundle ----------
FROM node:22-slim AS frontend-builder
WORKDIR /web
COPY src/frontend/package.json src/frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY src/frontend/ ./
RUN npm run build

FROM backend
COPY --from=frontend-builder /web/dist/ /app/src/frontend/dist/

EXPOSE 8765
CMD ["python", "src/python/server.py"]