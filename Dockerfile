# Imagen base liviana con Python
FROM python:3.11-slim
WORKDIR /app

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

RUN mkdir -p /app/resultados && chmod 777 /app/resultados

# Comando de arranque
CMD ["python", "bot.py"]
