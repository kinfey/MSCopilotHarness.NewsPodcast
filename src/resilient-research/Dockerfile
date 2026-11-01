FROM ghcr.io/astral-sh/uv:0.11.7 AS uv
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /bin/
WORKDIR /app/user_agent
ENV PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
COPY pyproject.toml uv.lock uv.toml ./
RUN uv sync --frozen --no-dev --no-install-project
COPY main.py ./
COPY station/ ./station/
EXPOSE 8088
CMD ["/app/user_agent/.venv/bin/python", "main.py"]
