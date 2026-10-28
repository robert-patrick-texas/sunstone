# Builder image for the Sunstone .deb, following vakr's.
#
# The package is assembled inside a clean Ubuntu 26.04 container, so the
# result depends only on pinned inputs: uv (which pins and checksum-verifies
# the python-build-standalone interpreter), nfpm, Node.js for the web UI
# build, and the hashed lockfiles (backend/uv.lock, frontend/package-lock.json).
# lintian and systemd-analyze come from the Ubuntu archive and only inspect
# the result.
#
# Build it with no context: docker build -t sunstone-deb-builder - < packaging/Dockerfile

ARG BASE_IMAGE=ubuntu:26.04

# nfpm v2.48.0, built statically. `go install` verifies every module against
# the Go checksum database, so a tampered module fails the build.
FROM golang:1.27.3@sha256:957861185dbf29d93668ace41e011d091c6e779953d47f0316ef2cc58e28fe2b AS nfpm
RUN CGO_ENABLED=0 GOBIN=/out go install github.com/goreleaser/nfpm/v2/cmd/nfpm@v2.48.0

# uv 0.13.6, pinned by image digest.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

# Node.js 24.22.1, frontend/.node-version, pinned by image digest. It only
# builds the web UI; the package ships the built files and never Node.
FROM node:24.22.1-trixie-slim@sha256:43b9ba1142b8dcf33fa8f922ca1be85714adc444e0586c7cf7726daaeabc1bea AS node

FROM ${BASE_IMAGE}
# binutils provides readelf for the glibc symbol-version gate in build.sh.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        binutils ca-certificates lintian systemd \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/
COPY --from=nfpm /out/nfpm /usr/local/bin/nfpm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && node --version && npm --version
