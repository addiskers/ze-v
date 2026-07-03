# ---- stage 1: build the React admin SPA (admin/ -> admin/dist) ----
FROM node:20-slim AS spa
WORKDIR /spa
COPY admin/ ./
RUN npm ci || npm install
RUN npm run build            # emits /spa/dist

# ---- stage 2: python runtime ----
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DATA_DIR=/var/eo-data

# Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install -r requirements.txt

# app code
COPY . .
# drop in the pre-built SPA (FastAPI serves it at /admin)
COPY --from=spa /spa/dist ./admin/dist

# persistent data (SQLite eo.db + JSON call logs) lives here; mount a volume on it
RUN mkdir -p /var/eo-data
VOLUME ["/var/eo-data"]

EXPOSE 8000
# ONE worker — the callback scheduler + campaign runner are in-process singletons
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
