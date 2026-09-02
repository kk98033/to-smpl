ARG BASE_IMAGE=nvcr.io/nvidia/pytorch:26.02-py3-igpu
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/to-smpl

COPY pyproject.toml README.md ./
RUN python -m pip install --no-cache-dir "numpy>=1.24,<2" \
 && python -m pip install --no-cache-dir --no-build-isolation "chumpy>=0.70" \
 && python -m pip install --no-cache-dir "scipy>=1.10" "smplx>=0.1.28"

COPY smpl_0901 ./smpl_0901
RUN python -m pip install --no-cache-dir --no-deps .
RUN python -c "import smpl_0901.service; import chumpy; import torch; print(torch.__version__)"

ENTRYPOINT ["smpl-0901-bridge"]
CMD ["--input", "udp://0.0.0.0:9100", "--smpl-dir", "/models", "--device", "cuda"]
