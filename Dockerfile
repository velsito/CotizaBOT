# 1. Imagen base liviana con Python
FROM python:3.11-slim

# 2. Evita archivos .pyc y mejora logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 5. Instalamos dependencias
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 user
USER user 
ENV PATH="/home/user/.local/bin:${PATH}"
# 3. Directorio de trabajo dentro del contenedor
WORKDIR /cotizaciones
# 4. Copiamos dependencias primero (mejor cache)
COPY --chown=user requirements.txt .

# 6. Copiamos el resto del código
COPY --chown=user . .

# 8. Comando de arranque
CMD ["python", "bot.py"]
