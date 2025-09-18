FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

# ---- System deps for headless Chrome ----
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    gnupg \
    unzip \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgdk-pixbuf-2.0-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxfixes3 \
    libxshmfence1 \
    libgbm1 \
    libgtk-3-0 \
    libglib2.0-0 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# ---- Add Google Chrome repo & install Chrome ----
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-linux-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && apt-get install -y google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# ---- Install ChromeDriver (v140.0.7339.0 to match Chrome 140) ----
RUN wget -q https://storage.googleapis.com/chrome-for-testing-public/140.0.7339.0/linux64/chromedriver-linux64.zip && \
    unzip chromedriver-linux64.zip && \
    mv chromedriver-linux64/chromedriver /usr/bin/chromedriver && \
    chmod +x /usr/bin/chromedriver && \
    rm -rf chromedriver-linux64* chromedriver-linux64.zip

# ---- Environment for your script ----
ENV CHROME_PATH=/usr/bin/google-chrome
ENV CHROME_DRIVER_PATH=/usr/bin/chromedriver

# ---- App setup ----
WORKDIR /app
COPY . /app

# ---- Python deps ----
RUN pip install --no-cache-dir -r requirements.txt

# ---- Start bot ----
CMD ["python", "main.py"]
