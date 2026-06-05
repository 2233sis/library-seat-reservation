FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p instance templates static

# Hugging Face Spaces requires port 7860; locally we override via -e PORT=5000.
EXPOSE 7860

ENV PORT=7860 \
    FLASK_HOST=0.0.0.0

# Use $PORT so the same image runs on HF Spaces (7860) and locally (-e PORT=5000).
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 app:app
