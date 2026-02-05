"""
Procesador de Esquemas Unifilares 
Devuelve en una serie de imagenes en formato png los fragmentos procesados.
"""

import fitz  # PyMuPDF
import io
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field
from enum import Enum
import logging
from PIL import Image
import json

# logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ConfiguracionProcesamiento:
    dpi: int = 300
    grilla_filas: int = 2
    grilla_columnas: int = 2
    overlap_px: int = 60  # Aumentado para no cortar símbolos técnicos
    corte_superior: float = 0.5 # Descartar mitad superior (Topográfico)
    formato_salida: str = "PNG"

@dataclass
class FragmentoImagen:
    """Contenedor de datos para enviar a Gemini o guardar en Docker"""
    datos: bytes
    posicion: Tuple[int, int]
    bbox: Tuple[int, int, int, int]
    pagina: int
    ancho: int
    alto: int
    metadata: Dict = field(default_factory=dict)
    x_offset: int = 0
    y_offset: int = 0

class ProcesadorEsquemaUnifilar:
    def __init__(self, config: ConfiguracionProcesamiento = None):
        self.config = config or ConfiguracionProcesamiento()

    def procesar_pdf(self, pdf_path: str) -> List[FragmentoImagen]:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo: {pdf_path}")
        
        fragmentos_totales = []
        doc = fitz.open(str(pdf_path))
        
        for num_pagina in range(len(doc)):
            logger.info(f"Procesando página {num_pagina + 1}")
            
            # 1. Renderizado con normalización física de rotación
            imagen_completa = self._renderizar_y_normalizar(doc[num_pagina])
            
            # 2. Segmentación: Tomar solo la mitad inferior (Unifilar)
            imagen_unifilar = self._extraer_mitad_inferior(imagen_completa)
            
            # 3. Fragmentación en teselas para detalle fino
            fragmentos = self._fragmentar(imagen_unifilar, num_pagina)
            fragmentos_totales.extend(fragmentos)
            
        doc.close()
        return fragmentos_totales

    def _renderizar_y_normalizar(self, pagina: fitz.Page) -> Image.Image:
        """
        Garantiza que la imagen resultante sea siempre horizontal (Landscape)
        para que el corte superior/inferior sea consistente.
        """
        zoom = self.config.dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        
        # Renderizado inicial
        pix = pagina.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))

        # Si la imagen es más alta que ancha (Vertical), la rotamos 90°
        # Esto asegura que el topográfico quede a la izquierda o arriba
        # y el unifilar sea accesible para el recorte.
        if img.height > img.width:
            logger.info("Detectada página vertical. Rotando para normalizar unifilar abajo.")
            img = img.rotate(90, expand=True)
            
        return img

    def _extraer_mitad_inferior(self, imagen: Image.Image) -> Image.Image:
        """Descarta el esquema topográfico (mitad superior)"""
        ancho, alto = imagen.size
        punto_corte = int(alto * self.config.corte_superior)
        
        # Crop: (left, top, right, bottom)
        return imagen.crop((0, punto_corte, ancho, alto))

    def _fragmentar(self, imagen: Image.Image, num_pag: int) -> List[FragmentoImagen]:
        ancho_total, alto_total = imagen.size
        ancho_t = ancho_total // self.config.grilla_columnas
        alto_t = alto_total // self.config.grilla_filas
        overlap = self.config.overlap_px
        
        fragmentos = []
        for f in range(self.config.grilla_filas):
            for c in range(self.config.grilla_columnas):
                x0 = max(0, c * ancho_t - overlap)
                y0 = max(0, f * alto_t - overlap)
                x1 = min(ancho_total, (c + 1) * ancho_t + overlap)
                y1 = min(alto_total, (f + 1) * alto_t + overlap)
                
                crop = imagen.crop((x0, y0, x1, y1))
                
                buffer = io.BytesIO()
                crop.save(buffer, format=self.config.formato_salida)
                
                fragmentos.append(FragmentoImagen(
                    datos=buffer.getvalue(),
                    posicion=(f, c),
                    bbox=(x0, y0, x1, y1),
                    pagina=num_pag,
                    ancho=x1 - x0,
                    alto=y1 - y0,
                    metadata={"tipo": "unifilar_inferior", "dpi": self.config.dpi},
                    
                    x_offset=x0,
                    y_offset=y0
                ))
        return fragmentos

    def guardar_en_disco(self, fragmentos: List[FragmentoImagen], carpeta: str):
        Path(carpeta).mkdir(parents=True, exist_ok=True)
        for frag in fragmentos:
            ruta = Path(carpeta) / f"frag_p{frag.pagina}_f{frag.posicion[0]}_c{frag.posicion[1]}.png"
            with open(ruta, "wb") as f:
                f.write(frag.datos)
        logger.info(f"Guardados {len(fragmentos)} fragmentos en {carpeta}")

def consolidar_conteo(lista_jsons):
    total_materiales = {}
    for resultado in lista_jsons:
        # Convertimos el texto de Gemini a diccionario de Python
        # unifica las salidas resultantes de las llamadas con cada fragmento en una sola respuesta con todas las cantidades encontradas
        datos = json.loads(resultado) 
        for material, cantidad in datos.items():
            total_materiales[material] = total_materiales.get(material, 0) + cantidad
    return total_materiales

# --- Ejecución de prueba ---
if __name__ == "__main__":
    procesador = ProcesadorEsquemaUnifilar()
    try:
        # Reemplaza con la ruta de tu PDF de prueba
        resultado = procesador.procesar_pdf("data/TOPO2.pdf")  # devuelve una lista con los resultados obtenidos
        procesador.guardar_en_disco(resultado, "resultados/fragmentos")
        print(f"Éxito: {len(resultado)} fragmentos listos para Gemini.")
    except Exception as e:
        print(f"Error: {e}")