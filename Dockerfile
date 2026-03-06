FROM python:3.10-slim

# Install system dependencies for Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libatspi2.0-0 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libxshmfence1 fonts-noto-cjk tor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium \
    && python -m playwright install-deps chromium

COPY . .

EXPOSE 8080

CMD bash -c "tor --SocksPort 9050 --DataDirectory /tmp/tor-data --Log 'notice stdout' &>/dev/null & sleep 5 && uvicorn main:app --host 0.0.0.0 --port 8080"
