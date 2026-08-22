# Use Microsoft's official Playwright image for Python (based on Ubuntu, with all browser dependencies pre-installed)
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Install git, build tools, curl, Node.js, yarn, and pnpm
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    make \
    gcc \
    g++ \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g yarn pnpm \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the Chromium browser binary
RUN playwright install chromium

# Copy the rest of the application code
COPY . .

# Expose port 8000
EXPOSE 8000

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

