FROM python:3.11-slim

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Pre-fetch the nano model so the demo does not need runtime network access.
# The detector still downloads at runtime as a fallback if this step was skipped.
ARG MODEL_URL=https://github.com/ultralytics/yolov5/releases/download/v7.0/yolov5n.onnx
RUN mkdir -p /models \
    && python -c "import urllib.request; urllib.request.urlretrieve('${MODEL_URL}', '/models/yolov5n.onnx')" \
    || echo "model pre-fetch skipped; runtime download will be attempted"

ENV PYTHONUNBUFFERED=1
ENV MODEL_PATH=/models/yolov5n.onnx
CMD ["python", "run.py"]
