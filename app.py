"""
app.py
------
API REST con FastAPI para el análisis de planos unifilares eléctricos.

Endpoints:
    POST /analyze   →  Recibe una imagen PNG y devuelve el conteo de componentes.
    GET  /health    →  Health-check para Render.

Uso rápido:
    uvicorn app:app --host 0.0.0.0 --port 8000
"""

import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from analyzer import UnifilarAnalyzer

# ---------------------------------------------------------------------------
# Configuración de logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Variables de entorno (configura estas en Render → Environment)
# ---------------------------------------------------------------------------
MODEL_PATH   = os.getenv("MODEL_PATH",   "weights/best.pt")
DEVICE       = os.getenv("DEVICE",       "cpu")
CONFIDENCE   = float(os.getenv("CONFIDENCE", "0.3"))
OUTPUT_DIR   = os.getenv("OUTPUT_DIR",   "/tmp/outputs")
MAX_FILE_MB  = float(os.getenv("MAX_FILE_MB", "50"))   # límite de subida

# ---------------------------------------------------------------------------
# Ciclo de vida de la aplicación (carga el modelo UNA sola vez)
# ---------------------------------------------------------------------------
analyzer: UnifilarAnalyzer | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global analyzer
    logger.info("Inicializando UnifilarAnalyzer…")
    analyzer = UnifilarAnalyzer(
        model_path=MODEL_PATH,
        device=DEVICE,
        confidence_threshold=CONFIDENCE,
        output_dir=OUTPUT_DIR,
    )
    logger.info("Aplicación lista.")
    yield
    logger.info("Apagando aplicación.")


app = FastAPI(
    title="Unifilar Analyzer API",
    description="Detección de componentes eléctricos en planos unifilares con YOLOv8 + SAHI.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Infraestructura"])
async def health_check():
    """Health-check utilizado por Render para verificar que la app está activa."""
    return {"status": "ok", "model_loaded": analyzer is not None}


@app.post("/analyze", tags=["Análisis"])
async def analyze_image(file: UploadFile = File(...)):
    """
    Analiza un plano unifilar eléctrico PNG.

    - **file**: Imagen PNG de alta resolución (máx. 50 MB por defecto).

    Devuelve:
    ```json
    {
        "counts": {"Disyuntor": 5, "Relé": 2},
        "total_components": 7,
        "annotated_image_url": "/result/annotated_plano.png"
    }
    ```
    """
    if analyzer is None:
        raise HTTPException(status_code=503, detail="Modelo aún no inicializado.")

    # Validar tipo de archivo
    if file.content_type not in ("image/png", "image/jpeg", "image/jpg"):
        raise HTTPException(
            status_code=415,
            detail="Formato no soportado. Use PNG o JPEG.",
        )

    # Verificar tamaño sin cargar todo en RAM de golpe
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=Path(file.filename or "upload.png").suffix
        ) as tmp:
            tmp_path = Path(tmp.name)
            size_mb = 0.0
            chunk_size = 1024 * 1024  # 1 MB
            while chunk := await file.read(chunk_size):
                size_mb += len(chunk) / (1024 * 1024)
                if size_mb > MAX_FILE_MB:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Archivo demasiado grande (máx. {MAX_FILE_MB} MB).",
                    )
                tmp.write(chunk)

        logger.info("Archivo recibido: %s (%.1f MB)", file.filename, size_mb)

        # Ejecutar análisis
        result = analyzer.predict(str(tmp_path))

        return JSONResponse(
            content={
                "counts": result["counts"],
                "total_components": sum(result["counts"].values()),
                "annotated_image_url": f"/result/{Path(result['output_image_path']).name}",
            }
        )

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error durante el análisis.")
        raise HTTPException(status_code=500, detail=f"Error interno: {exc}") from exc
    finally:
        # Eliminar archivo temporal
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


@app.get("/result/{filename}", tags=["Resultados"])
async def get_result_image(filename: str):
    """Descarga la imagen anotada generada por /analyze."""
    image_path = Path(OUTPUT_DIR) / filename
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Imagen no encontrada.")
    return FileResponse(str(image_path), media_type="image/png")


# ---------------------------------------------------------------------------
# Punto de entrada local
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)