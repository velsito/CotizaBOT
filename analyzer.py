"""
Módulo de visión artificial para detección de componentes eléctricos
en planos unifilares de alta resolución usando YOLOv8 + SAHI.

Optimizado para entornos con RAM limitada.
"""

import gc
import logging
import os
from collections import Counter
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# SAHI imports
from sahi import AutoDetectionModel
from sahi.predict import get_sliced_prediction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuración global
# ---------------------------------------------------------------------------

SLICE_SIZE = 640          # Tamaño del slice (coincide con el entrenamiento)
OVERLAP_RATIO = 0.2       # 20 % de solapamiento horizontal y vertical
CONFIDENCE_THRESHOLD = 0.4
IOU_THRESHOLD = 0.7 # aumentar para modificar la tolerancia a cajas solapadas

# Paleta de colores por clase (BGR para OpenCV)
CLASS_COLORS: dict[str, tuple[int, int, int]] = {
    "Térmica":      (0,   165, 255),   # naranja
    "Luminaria":           (0,   255,   0),   # verde
    "Fusible":  (255,   0,   0),   # azul
    "Disyuntor":    (0,   255, 255),   # amarillo
    "Guardamotor":        (255,   0, 255),   # magenta
    "Seccionador":        (255, 255,   0),   # cian
    "Contactor":          (128, 128, 255),   # lila
    "Fotocelula":          (200, 200, 200),   # gris
}
DEFAULT_COLOR = (0, 0, 255)             # rojo (clase desconocida)


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class UnifilarAnalyzer:
    """
    Analizador de planos unifilares eléctricos.

    Carga el modelo YOLOv8 una sola vez y reutiliza la instancia
    para múltiples inferencias, minimizando el uso de RAM.

    Parameters
    ----------
    model_path : str
        Ruta al archivo de pesos YOLOv8 (.pt).
    device : str
        Dispositivo de inferencia: ``"cpu"`` o ``"cuda:0"``.
    confidence_threshold : float
        Umbral mínimo de confianza para aceptar una detección.
    output_dir : str
        Directorio donde se guardarán las imágenes anotadas.
    """

    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        output_dir: str = "outputs",
    ) -> None:
        self.model_path = model_path
        self.device = device
        self.confidence_threshold = confidence_threshold
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Cargando modelo desde %s en dispositivo '%s'…", model_path, device)
        self.detection_model = AutoDetectionModel.from_pretrained(
            model_type="yolov8",
            model_path=model_path,
            confidence_threshold=confidence_threshold,
            device=device,
        )
        logger.info("Modelo cargado exitosamente.")

    # ------------------------------------------------------------------
    # Predicción principal
    # ------------------------------------------------------------------

    def predict(self, image_path: str) -> dict:
        """
        Ejecuta la inferencia con SAHI sobre una imagen de alta resolución.

        Parameters
        ----------
        image_path : str
            Ruta a la imagen PNG (puede ser de cualquier resolución).

        Returns
        -------
        dict con las claves:
            - ``counts``  : ``{"Disyuntor": 5, "Relé": 2, …}``
            - ``output_image_path`` : ruta de la imagen anotada guardada en disco.
            - ``detections`` : lista de detecciones crudas (para auditoría).
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Imagen no encontrada: {image_path}")

        logger.info("Iniciando análisis de '%s'…", image_path.name)

        # 1. Inferencia con SAHI (sliced prediction)
        result = get_sliced_prediction(
            str(image_path),
            self.detection_model,
            slice_height=SLICE_SIZE,
            slice_width=SLICE_SIZE,
            overlap_height_ratio=OVERLAP_RATIO,
            overlap_width_ratio=OVERLAP_RATIO,
            perform_standard_pred=True,   # predicción global además de slices
            postprocess_type="GREEDYNMM", # fusión de detecciones solapadas
            postprocess_match_metric="IOU",
            postprocess_match_threshold=IOU_THRESHOLD,
            verbose=0,
        )

        # 2. Extraer detecciones
        detections = _parse_detections(result)

        # 3. Conteo de materiales
        counts = count_materials(detections)

        # 4. Dibujar cajas sobre la imagen original
        output_image_path = self._draw_and_save(image_path, detections)

        # 5. Limpieza explícita de memoria
        del result
        _free_memory()

        logger.info("Análisis completado. Detecciones: %s", counts)
        return {
            "counts": counts,
            "output_image_path": str(output_image_path),
            "detections": detections,
        }

    # ------------------------------------------------------------------
    # Dibujo y guardado
    # ------------------------------------------------------------------

    def _draw_and_save(
        self,
        image_path: Path,
        detections: list[dict],
    ) -> Path:
        """
        Lee la imagen original, dibuja las detecciones y la guarda en disco.

        Se usa ``IMREAD_UNCHANGED`` para preservar la resolución completa
        y se libera el array de NumPy en cuanto termina el guardado.
        """
        img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise ValueError(f"OpenCV no pudo leer la imagen: {image_path}")

        # Convertir a BGR si la imagen viene en escala de grises o RGBA
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        for det in detections:
            _draw_box(img, det)

        output_path = self.output_dir / f"annotated_{image_path.name}"
        cv2.imwrite(str(output_path), img)

        # Liberar el array de imagen inmediatamente
        del img
        gc.collect()

        logger.info("Imagen anotada guardada en '%s'.", output_path)
        return output_path


# ---------------------------------------------------------------------------
# Funciones de utilidad
# ---------------------------------------------------------------------------

def _parse_detections(sahi_result) -> list[dict]:
    """
    Convierte el resultado de SAHI a una lista de diccionarios planos.

    Cada elemento contiene:
        ``label``, ``confidence``, ``x1``, ``y1``, ``x2``, ``y2``
    Las coordenadas ya están mapeadas a la imagen original por SAHI.
    """
    detections = []
    for obj in sahi_result.object_prediction_list:
        bbox = obj.bbox          # sahi.annotation.BoundingBox
        detections.append(
            {
                "label":      obj.category.name,
                "confidence": round(float(obj.score.value), 4),
                "x1":         int(bbox.minx),
                "y1":         int(bbox.miny),
                "x2":         int(bbox.maxx),
                "y2":         int(bbox.maxy),
            }
        )
    return detections


def count_materials(detections: list[dict]) -> dict[str, int]:
    """
    Devuelve un diccionario con el conteo de cada clase detectada.

    Parameters
    ----------
    detections : list[dict]
        Lista de detecciones generada por ``_parse_detections``.

    Returns
    -------
    dict ordenado de mayor a menor frecuencia.
    """
    counter = Counter(det["label"] for det in detections)
    return dict(counter.most_common())


def _draw_box(img: np.ndarray, det: dict) -> None:
    """Dibuja una caja anotada con clase y confianza sobre ``img`` (in-place)."""
    color = CLASS_COLORS.get(det["label"], DEFAULT_COLOR)
    x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]

    # Escalar grosor según la resolución de la imagen
    thickness = max(2, img.shape[1] // 1000)
    font_scale = max(0.5, img.shape[1] / 3000)

    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)

    label_text = f"{det['label']} {det['confidence']:.0%}"
    (tw, th), baseline = cv2.getTextSize(
        label_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
    )
    # Fondo del texto
    cv2.rectangle(img, (x1, y1 - th - baseline - 4), (x1 + tw, y1), color, -1)
    cv2.putText(
        img, label_text,
        (x1, y1 - baseline - 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (255, 255, 255),
        thickness,
    )


def _free_memory() -> None:
    """Libera memoria de Python y CUDA (si aplica)."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            logger.debug("Caché CUDA vaciado.")
    except ImportError:
        pass  # torch no está disponible, no es necesario