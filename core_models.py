import pandas as pd
import os 
from pydantic import BaseModel, Field
import logging
from typing import Dict, List, Tuple, Optional
from pathlib import Path

file_name = 'tableros.xlsm'
BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)

_datos_cache: Optional[Dict[str, pd.DataFrame]] = None
ruta_excel = BASE_DIR / "data" / file_name

if not ruta_excel.exists():
    print(f"❌ ERROR CRÍTICO: El archivo no existe en la ruta especificada.")
    # Imprimimos qué archivos SI hay en la carpeta data para debuguear
    if (BASE_DIR / "data").exists():
        print(f"📂 Archivos encontrados en data/: {os.listdir(BASE_DIR / 'data')}")

def cargar_datos(force_reload: bool = False) -> Dict[str, pd.DataFrame]:
    """
    Carga todas las hojas necesarias desde Excel usando Pandas.
    Usa caché para evitar recargas innecesarias.
    """
    global _datos_cache
    
    # 1. Retornar caché si existe y no se fuerza la recarga
    if _datos_cache is not None and not force_reload:
        logger.info("📦 Usando datos en caché (Pandas Memory)")
        return _datos_cache
    
    logger.info(f"📂 Cargando datos desde el archivo: {ruta_excel}")
    
    try:
        # 2. Usar pd.ExcelFile para abrir el archivo una sola vez
        # engine='openpyxl' es esencial para archivos .xlsm
        with pd.ExcelFile(ruta_excel, engine='openpyxl') as xls:
            
            hojas_config = {
                'seleccionadores': 'SELECCIONADORES',
                'envolventes': 'ENVOLVENTES',
                'termicas': 'TERMICAS',
                'diferencial': 'DIFERENCIAL',
                'modular': 'MODULAR',
                'estanco': 'ESTANCO',
                'bd_maestra': 'Base de datos'
            }
            
            datos = {}
            nombres_reales_en_excel = xls.sheet_names
            
            for key, nombre_hoja in hojas_config.items():
                try:
                    # Verificar si la hoja existe en el archivo
                    if nombre_hoja not in nombres_reales_en_excel:
                        logger.warning(f"⚠️  Hoja '{nombre_hoja}' no encontrada en el Excel, omitiendo...")
                        continue
                    
                    # Leer la hoja directamente a DataFrame
                    df = pd.read_excel(xls, sheet_name=nombre_hoja)
                    
                    # Limpiar nombres de columnas (quitar espacios en blanco)
                    df.columns = [str(c).strip() for c in df.columns]
                    
                    # Guardar en diccionario
                    datos[key] = df
                    logger.info(f"✅ Cargada '{nombre_hoja}': {len(df)} registros")
                    
                except Exception as e:
                    logger.error(f"❌ Error procesando hoja '{nombre_hoja}': {e}")
                    continue
        
        # 3. Validar hojas críticas
        hojas_criticas = ['seleccionadores', 'envolventes', 'termicas', 'diferencial', 'bd_maestra']
        faltantes = [h for h in hojas_criticas if h not in datos]
        
        if faltantes:
            raise ValueError(f"Faltan hojas críticas requeridas: {', '.join(faltantes)}")
        
        # 4. Guardar en caché y retornar
        _datos_cache = datos
        logger.info(f"🚀 Carga completa exitosa: {len(datos)} hojas en memoria RAM")
        return datos
        
    except FileNotFoundError:
        logger.error(f"❌ No se encontró el archivo Excel: {ruta_excel}")
        raise
    except Exception as e:
        logger.exception(f"❌ Error crítico en cargar_datos")
        raise

# === VALIDACIÓN ===

class MaterialInput(BaseModel):
    """Material a procesar"""
    categoria: str = Field(description="DIF o TERM")
    cantidad: int = Field(gt=0, description="Cantidad de dispositivos")
    polos: str = Field(description="Cantidad de polos (2P, 3P, 4P)")
    amperaje: str = Field(description="Corriente nominal")
    familia: str = Field(description="Familia del dispositivo")
    superinmunizado: bool = Field(default=False, description="Solo para diferenciales")


class ConfiguracionInput(BaseModel):
    """Configuración del tablero"""
    seleccionador_ref: str = Field(description="Referencia del seleccionador")
    tiene_borneras: bool = Field(default=True)
    aplicar_reserva: bool = Field(default=True, description="Aplicar reserva del 15%")
    tipo_contrafrente: str = Field(default="METALICO")


class CalculoRielesInput(BaseModel):
    """Parámetros para cálculo de rieles"""
    largo_riel_mm: float = Field(gt=0, description="Largo del riel en mm")
    ancho_seleccionador_mm: float = Field(gt=0, description="Ancho del seleccionador")
    anchos_diferenciales_mm: List[float] = Field(default_factory=list)
    anchos_termicas_mm: List[float] = Field(default_factory=list)
    tiene_borneras: bool = Field(default=True)
    aplicar_reserva: bool = Field(default=True)