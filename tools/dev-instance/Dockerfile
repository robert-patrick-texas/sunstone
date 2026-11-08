# The Sunstone dev instance's image: Node.js and uv pinned as the package
# build pins them (packaging/Dockerfile), and rsync to copy the web UI's
# source. uv brings the Python that backend/.python-version names. The
# working tree is mounted at run time (compose.yaml), never copied in.

# uv 0.13.6, pinned by image digest.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

# Node.js 24.22.1, frontend/.node-version, pinned by image digest.
FROM node:24.22.1-trixie-slim@sha256:43b9ba1142b8dcf33fa8f922ca1be85714adc444e0586c7cf7726daaeabc1bea
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends rsync \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
# The image's node account runs everything. Its directories exist here, so the
# named volumes mounted on them start out owned by it.
RUN install -d -o node -g node /venv /work /state /home/node/.cache
COPY run.sh /usr/local/bin/sunstone-dev
USER node
ENV UV_PROJECT_ENVIRONMENT=/venv \
    UV_CACHE_DIR=/home/node/.cache/uv \
    UV_PYTHON_INSTALL_DIR=/home/node/.cache/python \
    UV_LINK_MODE=copy \
    npm_config_cache=/home/node/.cache/npm \
    npm_config_update_notifier=false
CMD ["sunstone-dev"]
