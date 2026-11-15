# Multi-stage build: C++ solver → Python backend.
# The SPA is built separately in Dockerfile.frontend.
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
    numpy pydantic python-dotenv websockets httpx openai

COPY --from=cpp-builder /usr/local/lib/triage_core*.so /usr/local/lib/
ENV LD_LIBRARY_PATH=/usr/local/lib
ENV PYTHONPATH=/usr/local/lib

COPY src/shared/ /app/src/shared/
COPY src/python/ /app/src/python/
WORKDIR /app

# The SPA is built and served by Dockerfile.frontend (compose `frontend`
# service); this image only runs the WebSocket backend and the C++ solver.

EXPOSE 8765
CMD ["python", "src/python/server.py"]
