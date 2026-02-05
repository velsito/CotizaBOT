# Imagen base liviana con Python
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y libgl1 libglib2.0-0 poppler-utils build-essential && rm -rf /var/liub/apt/lists/*

# Evita archivos .pyc y mejora logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /app/resultados && chmod 777 /app/resultados
RUN mkdir -p /app/data && chmod 777 /app/data

# Copiamos dependencias primero (mejor cache)
COPY requirements.txt .

# Instalamos dependencias
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 user
USER user 
ENV PATH="/home/user/.local/bin:${PATH}"

# Copiamos el resto del código
COPY . .

EXPOSE 10000

# Comando de arranque
CMD ["python", "bot.py"]
