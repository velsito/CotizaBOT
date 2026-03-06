# Imagen base liviana con Python
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 poppler-utils build-essential && rm -rf /var/liub/apt/lists/*
RUN mkdir -p /app/data /app/resultados /app/temp_pdf

# Evita archivos .pyc y mejora logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copiamos dependencias primero (mejor cache)
COPY requirements.txt .

# Instalamos dependencias
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 user
USER user 
ENV PATH="/home/user/.local/bin:${PATH}"

# Copiamos el resto del código
COPY . .

RUN chmod -R 777 /app/data /app/resultados /app/temp_pdf || true

# Comando de arranque
CMD ["python", "bot.py"]

