# 1. Imagen base liviana con Python
FROM python:3.11-slim

WORKDIR /cotizaciones

# 2. Evita archivos .pyc y mejora logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 4. Copiamos dependencias primero (mejor cache)
COPY requirements.txt .

# 5. Instalamos dependencias
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 user
USER user 
ENV PATH="/home/user/.local/bin:${PATH}"
# 3. Directorio de trabajo dentro del contenedor

# 6. Copiamos el resto del código
COPY . .

# 8. Comando de arranque
CMD ["python", "bot.py"]
