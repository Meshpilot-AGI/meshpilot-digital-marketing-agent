# MeshPilot channel gateway — a tiny always-on Discord↔agent bridge (Railway).
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bridge.py .

# No inbound HTTP — this is a Discord gateway (websocket) client. Just run it.
CMD ["python", "-u", "bridge.py"]
