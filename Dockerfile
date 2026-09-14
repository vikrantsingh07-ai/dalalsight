# DalalSight API + built dashboard in one container, for a backend host such as Render, Railway, Fly.io or a VPS.
#   docker build -t dalalsight .
#   docker run -p 8765:8765 --env-file .env -e CC_ACCESS_TOKEN=<long random string> -v cc-data:/app/data dalalsight
# The server refuses to listen on 0.0.0.0 without CC_ACCESS_TOKEN. Hosts that set PORT are honoured.

FROM node:22-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CC_HOST=0.0.0.0 \
    CC_DEV_MODE=false
WORKDIR /app
COPY packages/tradingagents packages/tradingagents
COPY pyproject.toml ./
COPY backend backend
# Editable installs keep the source layout, which the app uses to find web/dist, tradingview/ and data/.
RUN pip install -e packages/tradingagents -e .
COPY tradingview tradingview
COPY --from=web /app/web/dist web/dist
EXPOSE 8765
CMD ["python", "-m", "cc"]
