FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim


WORKDIR "/app"

COPY . .

RUN uv sync

EXPOSE 80/tcp

CMD ["uv", "run", "uvicorn", "--host", "0.0.0.0", "--port", "80", "server:app"]