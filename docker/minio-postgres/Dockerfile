FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    FAKE_FREE_BYTES=10995116277760 \
    DATA_ROOT=/data \
    MINIO_MOUNT=/mnt/minio \
    MINIO_ROOT_USER=minioadmin \
    MINIO_ROOT_PASSWORD=minioadmin \
    POSTGRES_USER=agent \
    POSTGRES_PASSWORD=agent \
    POSTGRES_DB=agent_constructor \
    POSTGRES_PORT=5432

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        e2fsprogs \
        fuse3 \
        gcc \
        libfuse3-dev \
        pkg-config \
        postgresql \
        postgresql-contrib \
        supervisor \
        mount \
        procps \
        gosu \
    && rm -rf /var/lib/apt/lists/*

# MinIO server binary
RUN curl -fsSL https://dl.min.io/server/minio/release/linux-amd64/minio \
        -o /usr/local/bin/minio \
    && chmod +x /usr/local/bin/minio \
    && minio --version

COPY fuse/libfakefreespace.c fuse/fakefreespace_passthrough.c /tmp/fuse/
RUN gcc -O2 -Wall -fPIC -shared /tmp/fuse/libfakefreespace.c \
        -o /usr/local/lib/libfakefreespace.so -ldl \
    && gcc -O2 -Wall /tmp/fuse/fakefreespace_passthrough.c \
        -o /usr/local/bin/fakefreespace-mount \
        $(pkg-config --cflags --libs fuse3) \
    && rm -rf /tmp/fuse \
    && echo "user_allow_other" >> /etc/fuse.conf

COPY entrypoint.sh /entrypoint.sh
COPY supervisord.conf /etc/supervisor/supervisord.conf
RUN sed -i 's/\r$//' /entrypoint.sh /etc/supervisor/supervisord.conf \
    && chmod +x /entrypoint.sh \
    && mkdir -p /data /mnt/minio /var/log/supervisor /etc/supervisor/conf.d

EXPOSE 5432 9000 9001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD bash -c 'pg_isready -h 127.0.0.1 -p 5432 && curl -fsS http://127.0.0.1:9000/minio/health/live >/dev/null'

ENTRYPOINT ["/entrypoint.sh"]
