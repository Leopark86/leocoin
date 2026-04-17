FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 브라우저는 베이스 이미지에 포함되어 있으므로
# playwright install 불필요

COPY . .

CMD ["python", "main.py"]
