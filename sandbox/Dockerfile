# Immutable runner image. Everything the graded code needs is baked in at build
# time because the container runs with no network and a read-only root filesystem.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install pytest==8.3.5

WORKDIR /workspace
# The runtime policy also forces --user 65534:65534; this is the fallback default.
USER 65534:65534
CMD ["python", "--version"]
