# Perch app (API, web app, in-process brief jobs). No GPU: in the S9 hybrid deployment the
# models run on the host as systemd user units (deploy/systemd/demo/), reached over
# localhost because the container uses the host network (docker-compose.yml).
# Base images pinned by digest (review S18): the tag can move, the digest cannot.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --extra anthropic --no-install-project
COPY perch ./perch
COPY web ./web
RUN uv sync --frozen --no-dev --extra anthropic
CMD ["/opt/venv/bin/perch", "serve", "--host", "127.0.0.1", "--port", "8090"]
