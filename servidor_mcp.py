import asyncio
import logging
import datetime
from datetime import datetime
import pandas as pd
from io import BytesIO
from typing import List, Dict
import json
from typing import List, Dict, Any
import fitz
import math
import copy

# Configuración de Gemini API
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv
from pathlib import Path

from core_models import cargar_datos, MaterialInput, ConfiguracionInput, CalculoRielesInput

# Importar las clases del dimensionador
from dimensionador_tableros import (
    ExcelDataLoader,
    CalculadorRieles,
    SelectorGabinete,
    ProcesadorMateriales,
    EscritorResultados,
    ConfiguracionTablero,
    TipoTablero,
    Material,
    Gabinete
)

# Configuración
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-tableros-gemini")
BASE_DIR = Path(__file__).resolve().parent
FILE_NAME = 'tableros.xlsm'

OUTPUT_DIR = BASE_DIR / "resultados"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)  # Crear carpeta si no existe

try:
    os.chmod(OUTPUT_DIR, 0o777)
except:
    pass

class EstadoRecoleccion:
    """Clase para mantener el estado de la recolección de datos"""
    def __init__(self):
        self.en_proceso = False
        self.callback_pendiente = None
        self.datos_recolectados = None
        
estados_usuarios = {}

def obtener_estado(chat_id:int) -> EstadoRecoleccion:
    """Obtiene o crea el estado de recolección para un chat_id"""
    if chat_id not in estados_usuarios:
        estados_usuarios[chat_id] = EstadoRecoleccion()
    return estados_usuarios[chat_id]

def resetear_estado_recoleccion(chat_id:int):
    if chat_id in estados_usuarios:
        del estados_usuarios[chat_id] # Eliminar estado para ese chat_id
        logger.info(f"✅ Estado de recolección reseteado para chat_id {chat_id}")

def registrar_callback_recoleccion(callback_func):
    # se llama desde bot para registrar la función de callback al inicializar
    global _callback_recoleccion 
    _callback_recoleccion = callback_func
    logger.info("callback recoleccion registrado")

_callback_recoleccion = None

# Almacenamiento temporal para datos en edición
datos_en_edicion = {
    "config": None,
    "materiales": None
}

def guardar_datos_en_edicion(config: dict, materiales: list):
    """Guarda datos para edición"""
    global datos_en_edicion
    datos_en_edicion["config"] = copy.deepcopy(config) if config else {}
    datos_en_edicion["materiales"] = copy.deepcopy(materiales) if materiales else []
    logger.info(f"📝 Guardados {len(datos_en_edicion['materiales'])} materiales")

def obtener_datos_en_edicion():
    """Obtiene datos en edición con DEEP COPY"""
    return copy.deepcopy(datos_en_edicion)  # ✅ FIX AQUÍ

def get_tools_declarations():
    """
    Retorna las declaraciones de tools como declaraciones JSON para que Gemini pueda tomarlas
    """
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="iniciar_recoleccion_interactiva", # tool para iniciar recolección
                    description="Inicia el proceso interactivo de recolección de datos para dimensionar un tablero eléctrico. El usuario responderá mediante botones en Telegram.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "chat_id": {
                                "type": "string",
                                "description": "ID del chat de Telegram donde se iniciará el proceso de recolección"
                            }
                        },
                        
                    }
                ),
                types.FunctionDeclaration(
                    name="buscar_seleccionador",
                    description="Busca un seleccionador por su referencia",
                    parameters={
                        "type": "object",
                        "properties": {
                            "referencia": {
                                "type": "string",
                                "description": "Referencia del seleccionador"
                            }
                        },
                        "required": ["referencia"]
                    }
                ),
                types.FunctionDeclaration(
                    name="listar_gabinetes_disponibles",
                    description="Lista gabinetes disponibles por tipo",
                    parameters={
                        "type": "object",
                        "properties": {
                            "tipo": {
                                "type": "string",
                                "description": "ESTANCO, MODULAR o TODOS"
                            },
                            "ancho_minimo": {
                                "type": "number",
                                "description": "Ancho mínimo en mm"
                            },
                            "alto_minimo": {
                                "type": "number",
                                "description": "Alto mínimo en mm"
                            }
                        },
                        "required": ["tipo"]
                    }
                ),
                types.FunctionDeclaration(
                    name="validar_configuracion",
                    description="Valida una configuración antes de dimensionar",
                    parameters={
                        "type": "object",
                        "properties": {
                            "configuracion": {
                                "type": "object",
                                "properties": {
                                    "seleccionador_ref": {
                                        "type": "string"
                                    },
                                    "tiene_borneras": {
                                        "type": "boolean"
                                    },
                                    "aplicar_reserva": {
                                        "type": "boolean"
                                    }
                                },
                                "required": ["seleccionador_ref"]
                            },
                            "materiales": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "categoria": {"type": "string"},
                                        "cantidad": {"type": "integer"},
                                        "polos": {"type": "string"},
                                        "amperaje": {"type": "string"},
                                        "familia": {"type": "string"}
                                    },
                                    "required": ["categoria", "cantidad", "polos", "amperaje", "familia"]
                                }
                            }
                        },
                        "required": ["configuracion", "materiales"]
                    }
                ),
                types.FunctionDeclaration(
                    name="actualizar_datos",
                    description="Actualiza los datos de configuración y materiales para el dimensionamiento. Usa esto cuando el usuario quiera modificar valores de su configuración actual.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "config_updates": {
                                "type": "object",
                                "description": "Campos de configuración a actualizar. Puede contener: seleccionador_ref, tipo_gabinete, tiene_borneras, aplicar_reserva, tipo_contrafrente",
                                "properties": {
                                    "seleccionador_ref": {"type": "string"},
                                    "tipo_gabinete": {"type": "string"},
                                    "tiene_borneras": {"type": "boolean"},
                                    "aplicar_reserva": {"type": "boolean"},
                                    "tipo_contrafrente": {"type": "string"}
                                }
                            },
                            "materiales_agregar": {
                                "type": "array",
                                "description": "Materiales a agregar a la lista actual",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "categoria": {"type": "string"},
                                        "cantidad": {"type": "integer"},
                                        "polos": {"type": "string"},
                                        "amperaje": {"type": "string"},
                                        "familia": {"type": "string"},
                                        "superinmunizado": {"type": "boolean"}
                                    },
                                    "required": ["categoria", "cantidad", "polos", "amperaje", "familia"]
                                }
                            },
                            "materiales_eliminar_indices": {
                                "type": "array",
                                "description": "Índices de materiales a eliminar (ej: [0, 2])",
                                "items": {"type": "integer"}
                            },
                            "descripcion_cambios": {
                                "type": "string",
                                "description": "Descripción legible de los cambios realizados para mostrar al usuario"
                            }
                        }
                    }
                ),
                types.FunctionDeclaration(
                    name="analizar_esquema_unifilar",
                    description="Se activa automáticamente cuando se recibe la ruta de un archivo PDF que contiene esquemas unifilares y topográficos de tableros eléctricos. Realiza el conteo de materiales para el área de Cotizaciones.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "pdf_path": {
                                "type": "string",
                                "description": "Ruta completa al archivo PDF del esquema unifilar"
                           }
                        },
                        "required": ["pdf_path"]
                    }
                )
            ]
        )
    ]

# === MAPEO DE FUNCIONES ===

FUNCTION_MAP = {
    "iniciar_recoleccion_interactiva": None,  # Se define abajo
    "buscar_seleccionador": None,
    "listar_gabinetes_disponibles": None,
    "validar_configuracion": None,
    "actualizar_datos": None,
    "analizar_esquema_unifilar": None
}

# === IMPLEMENTACIÓN DE LAS FUNCIONES ===

async def analizar_esquema_unifilar1(pdf_path: str) -> Dict[str, Any]:
    
    """
    Analiza un esquema unifilar desde PDF en base64
    No requiere parámetros adicionales - todo es automático

    Returns:
        Diccionario con el análisis consolidado
    """

    from unifilar import ConfiguracionProcesamiento, ProcesadorEsquemaUnifilar, FragmentoImagen, consolidar_conteo

    temp_pdf_path = None
    inicio = asyncio.get_event_loop().time()
    
    # Variables de estado
    conteos_parciales = []
    errores = []
    fragmentos_procesados = 0
    fragmentos_fallidos = 0
    nombre_proyecto = Path(pdf_path).stem

    try:
         
        # ================================================================
        # CARGAR GUÍA 
        # ================================================================
        
        BASE_DIR = Path(__file__).resolve().parent.parent
        load_dotenv(dotenv_path=BASE_DIR / '.env')
        BASE_DIR = Path(__file__).resolve().parent.parent
        env_path = BASE_DIR / '.env'

        if not env_path.exists():
            env_path = Path('.env')  # Intentar desde directorio actual

        load_dotenv(dotenv_path=env_path)

        guia_env = os.getenv('GUIA_REFERENCIA_PATH')
        guia_path = Path(guia_env)
        if not guia_path.exists():
            raise FileNotFoundError(f"Guía no encontrada: {guia_path}")

        # ================================================================

        logger.info("Procesando PDF (DPI: 300, Grilla: 2x2)...")
        
        config = ConfiguracionProcesamiento(
            dpi=300,
            grilla_filas=2,
            grilla_columnas=2,
            overlap_px=2,
            corte_superior=0.5,
            formato_salida="PNG"
        )
        
        procesador = ProcesadorEsquemaUnifilar(config)
        
        pdf_path_obj = Path(pdf_path)  # Usar el parámetro que recibe la función

        fragmentos = await asyncio.to_thread(
            procesador.procesar_pdf,
            str(pdf_path_obj)  # ← Ruta válida del PDF
        )
        
        for idx, frag in enumerate(fragmentos, 1):
            print(f"Fragmento {idx}:")
            print(f"  x_offset: {frag.x_offset}")
            print(f"  y_offset: {frag.y_offset}")
            print(f"  bbox: {frag.bbox}")
            print(f"  tamaño: {frag.ancho}x{frag.alto}")
        
        if not fragmentos:
            raise ValueError("No se pudieron extraer fragmentos del PDF")
        
        carpeta_resultados = Path("resultados") / nombre_proyecto
                
        logger.info(f"Guardando fragmentos en: {carpeta_resultados}")
        await asyncio.to_thread(
            procesador.guardar_en_disco,
            fragmentos,
            str(carpeta_resultados)
        )

        total_fragmentos = len(fragmentos)
        logger.info(f"✅ {total_fragmentos} fragmentos extraídos")
        
        # ================================================================
        # 4. CONFIGURAR MODELO GEMINI
        # ================================================================

        
        # Prompt optimizado para detección de materiales
        PROMPT = """Eres un experto en análisis de esquemas eléctricos unifilares.  

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXTO 
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Estás analizando UN FRAGMENTO de un esquema más grande. Este fragmento puede contener:
- Elementos completos (cuenta estos)
- Elementos PARCIALMENTE CORTADOS en los bordes (NO cuentes estos)
- Símbolos repetidos que representan el MISMO material (consolida)

Tienes acceso a una GUÍA DE REFERENCIA con los símbolos estándar.
MATERIALES A CONTAR:
- termicas: disyuntores termomagnéticos
- luminarias:
    símbolo: círculo con cruz interna con una línea en su base
- fusible:
    símbolo: rectángulo pequeño atravesado por una línea, puede estar en vertical u horizontal
- disyuntores: Disyuntores diferenciales
- guardamotor: guardamotor
- contactor: contactor
- seccionador: seleccionador rotativo bajo carga 4 polos

REGLAS:
- a un mismo material pueden corresponderle varias representaciones que figuran en la guía, pero debes sumarlo al mismo elemento de conteo (por ejemplo el seccionador tiene 2 representaciones distintas pero hablan de lo mismo)
- Si un símbolo no está en la guía, etiquétalo como "Desconocido" y describe sus rasgos (ej. "contiene zigzag térmico").
- No inventes materiales por proximidad; si hay duda, reporta la incertidumbre.
- Nota sobre Orientación: Los símbolos en el plano pueden aparecer rotados (0°, 90°, 180°, 270°) dependiendo de si la línea de flujo es vertical u horizontal. Identifica los componentes por su morfología interna sin importar su orientación espacial respecto al marco de la imagen.
- Si ves un multiplicador numérico junto a un símbolo, el valor de 'cantidad' debe ser ese número, no 1

🚫 NO CUENTES:
1. Elementos cortados en los BORDES del fragmento (arriba, abajo, izquierda, derecha)
2. Líneas de conexión entre símbolos (a menos que tengan anotación de cantidad)

✅ SÍ CUENTA:
1. Símbolos COMPLETOS visibles dentro del fragmento
2 Elementos con toda su simbología visible (no cortados)

Responde ÚNICAMENTE con un objeto JSON válido, SIN texto adicional, SIN explicaciones, SIN markdown.
Estructura exacta:
{
    "termicas": 0, 
    "focos": 0, 
    "fusibles": 0, 
    "disyuntores": 0, 
    "guardamotor": 0, 
    "contactor": 0, 
    "seccionador": 0

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROCESO DE ANÁLISIS PASO A PASO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASO 1: ORIENTACIÓN
- Identifica si el fragmento es del UNIFILAR (símbolos eléctricos) o TOPOGRÁFICO (planta arquitectónica)
- Si es topográfico, retorna todo en 0
- Verifica la GUÍA DE REFERENCIA adjunta

PASO 2: IDENTIFICACIÓN DE BORDES
- Marca mentalmente qué elementos están COMPLETOS
- Descarta elementos cortados por los bordes del fragmento

PASO 3: CONTEO POR CATEGORÍA
Para CADA tipo de material:
  a) Busca el símbolo en la guía
  b) Identifica TODAS sus variantes en el fragmento
  c) Descarta los que están en bordes
  d) Cuenta SOLO los completos
  e) Verifica que no hayas contado duplicados

PASO 4: VALIDACIÓN FINAL
- ¿El total tiene sentido? (Ej: ¿20 térmicas en un fragmento pequeño? Revisar)
- ¿Contaste líneas de conexión como cables? (Error común)
- ¿Algún símbolo está duplicado con mismo ID? (Contar 1 sola vez)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECORDATORIOS FINALES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✓ Prioriza PRECISIÓN sobre cantidad
✓ Ante la duda, NO cuentes
✓ Un conteo bajo y preciso es mejor que uno alto e impreciso
✓ Revisa SIEMPRE la guía antes de contar
✓ Elementos en bordes = 0 (se contarán en fragmentos adyacentes)
✓ Responde SOLO con JSON, nada más

Ahora analiza el fragmento adjunto con estas reglas."""
        
        # ================================================================
        # 5. ANALIZAR FRAGMENTOS CON GEMINI
        # ================================================================
        
        logger.info("INICIANDO ANÁLISIS: ")

        model = client.models.generate_content
        guia_bytes = guia_path.read_bytes()
        print(f"✅ Éxito: Se obtuvieron {len(guia_bytes)} bytes.")
        
        for idx, fragmento in enumerate(fragmentos, start=1):
            try:
                logger.info(
                    f"[{idx}/{total_fragmentos}] Analizando página {fragmento.pagina}, "
                    f"posición {fragmento.posicion}"
                )
                
                contenido = [
                    { "text": PROMPT },
                    { 
                        "inline_data": {
                            "mime_type": "image/png", 
                            "data": guia_bytes  
                        }
                    },
                    { "text": "FRAGMENTO A ANALIZAR:" },
                    { 
                        "inline_data": {
                            "mime_type": "image/png", 
                            "data": fragmento.datos # Los bytes del renderizado del PDF
                        }
                    }
                ]

                # Llamada a Gemini usando el cliente ya configurado
                response = await asyncio.to_thread(
                    model,
                    model='gemini-2.0-flash',
                    contents=contenido,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        top_p=0.95,
                        top_k=40,
                        max_output_tokens=256,
                    )
                )

                texto = response.text.strip()
                
                # Remover markdown si existe
                if "```json" in texto:
                    texto = texto.split("```json")[1].split("```")[0]
                elif "```" in texto:
                    texto = texto.split("```")[1].split("```")[0]
                
                texto = texto.strip()
                
                # Parsear JSON
                try:
                    conteo = json.loads(texto)
                    
                    if not isinstance(conteo, dict):
                        raise ValueError(f"No es diccionario: {type(conteo)}")
                    
                    # Agregar a lista (como string para tu función consolidar_conteo)
                    conteos_parciales.append(texto)
                    fragmentos_procesados += 1
                    
                    # Log de materiales encontrados
                    encontrados = {k: v for k, v in conteo.items() if v > 0}
                    if encontrados:
                        logger.info(f"  → {encontrados}")
                    else:
                        logger.info(f"  → Sin materiales")
                
                except json.JSONDecodeError as je:
                    error_msg = f"Fragmento {idx}: JSON inválido - {str(je)}"
                    logger.error(error_msg)
                    errores.append(error_msg)
                    fragmentos_fallidos += 1
                
                # Rate limiting (1 segundo entre llamadas)
                if idx < total_fragmentos:
                    await asyncio.sleep(1.0)
                
            except Exception as e:
                error_msg = f"Fragmento {idx}: {str(e)}"
                logger.error(error_msg)
                errores.append(error_msg)
                fragmentos_fallidos += 1
                continue
        
        # ================================================================
        # 6. CONSOLIDAR CONTEOS
        # ================================================================
        
        logger.info("Consolidando resultados...")
        
        conteo_final = consolidar_conteo(conteos_parciales)
        
        logger.info(f"Conteo final: {conteo_final}")
        
        # ================================================================
        # 7. PREPARAR RESULTADO
        # ================================================================
        
        tiempo_total = asyncio.get_event_loop().time() - inicio
        
        resultado = {
            "status": "success" if fragmentos_procesados > 0 else "error",
            "proyecto": nombre_proyecto,
            "conteo_materiales": conteo_final,
            "metadatos": {
                "fragmentos_procesados": fragmentos_procesados,
                "fragmentos_fallidos": fragmentos_fallidos,
                "total_fragmentos": total_fragmentos,
                "tiempo_total_segundos": round(tiempo_total, 2),
                "timestamp": datetime.now().isoformat(),
                "configuracion": {
                    "dpi": 300,
                    "grilla": "4x4",
                    "overlap_px": 10
                }
            },
            "errores": errores
        }
        
        logger.info(
            f"✅ Análisis completado: {fragmentos_procesados}/{total_fragmentos} "
            f"fragmentos en {tiempo_total:.2f}s"
        )
        
        return resultado
        
    except Exception as e:
        logger.error(f"❌ Error crítico: {e}", exc_info=True)
        tiempo_total = asyncio.get_event_loop().time() - inicio
        
        # Intentar consolidar lo procesado
        conteo_parcial = {}
        if conteos_parciales:
            try:
                conteo_parcial = consolidar_conteo(conteos_parciales)
            except:
                pass
        
        return {
            "status": "error",
            "proyecto": nombre_proyecto,
            "conteo_materiales": conteo_parcial,
            "metadatos": {
                "fragmentos_procesados": fragmentos_procesados,
                "fragmentos_fallidos": fragmentos_fallidos,
                "total_fragmentos": fragmentos_procesados + fragmentos_fallidos,
                "tiempo_total_segundos": round(tiempo_total, 2),
                "timestamp": datetime.now().isoformat()
            },
            "errores": [str(e)] + errores
        }
    
    finally:
        # Limpiar archivo temporal
        if temp_pdf_path and Path(temp_pdf_path).exists():
            try:
                Path(temp_pdf_path).unlink()
                logger.debug("Archivo temporal eliminado")
            except Exception as e:
                logger.warning(f"No se pudo eliminar temporal: {e}")

PROMPT_ANALISIS =  """ Actúa como un sistema experto en visión artificial para la industria eléctrica. Tu objetivo es identificar, clasificar y localizar componentes en fragmentos de planos unifilares para un sistema de cotización automática.

Reglas de Localización:
Sistema de Coordenadas: Utiliza un plano de 0 a 1000 para ambos ejes (X e Y).
Punto de Origen: El punto (0,0) es la esquina superior izquierda del fragmento de imagen provisto.
Centro Geométrico: Debes calcular las coordenadas x e y basándote en el centro exacto del símbolo gráfico del componente detectado.

Consideraciones:
- Para componentes sin etiquetas (como luminarias y fusibles), guiate por su forma geométrica:
  Luminarias: "Detectar círculos que contengan una 'X' interna. Ignorar si la 'X' está fuera del círculo. Contabilizar cada aparición como una unidad de material aunque no posea etiqueta".
  Fusibles: "Detectar rectángulos estrechos atravesados por una línea longitudinal continua. No confundir con cables de conexión; el fusible siempre tiene un borde cerrado".
- Para cada componente sin etiqueta detectado, asigná un ID virtual siguiendo el esquema TIPO-COORDENADA. Ejemplo: LUM-250-400. Esto permitirá que el proceso de deduplicación lo trate como un objeto único y real.
- Por cada ícono de fusible y de luminaria, DEBES CONTAR 3 ELEMENTOS por cada símbolo individual correspondiente. 

Símbolos a identificar:
1. Térmica (Interruptor Automático)
Estructura principal: Una línea vertical interrumpida por un segmento diagonal (brazo del interruptor).
Rasgo distintivo superior: En el extremo de la línea superior, hay una pequeña "X" o asterisco. Justo 
encima de la "X", hay un guion horizontal corto. Rasgo distintivo inferior: El extremo del brazo diagonal 
termina en una forma de "escalera" o gancho con dos ángulos rectos.
Identificador: suele ir acompañado de TM y el número de térmica, y el amperaje, o de solo alguno de esos dos valores.
Ejemplo: -TM4 2x16A 

2. Iluminaria (Luminaria)
Estructura principal: Un círculo perfecto centrado sobre una línea vertical continua que lo atraviesa de polo a polo.
Contenido: Dentro del círculo, dos líneas diagonales se cruzan en el centro exacto, formando una "X" cuyos extremos
tocan el borde interior del círculo.
Identificador: puede figurar con una (R) próxima al símbolo y un x3, indicando que deben contarse 3 luminarias

3. Fusibles
Estructura principal: Un rectángulo vertical muy delgado y alargado.
Relación espacial: Una línea vertical atraviesa el rectángulo por su eje central, sobresaliendo tanto por la parte
superior como por la inferior. El interior del rectángulo suele ser vacío (blanco).
Identificador: pueden ir acompañados por el amperaje y la cantidad, ubicados próximos al símbolo.
Ejemplo: 2A x3 (debes contar 3 unidades para ese ícono)

4. Disyuntor (Diferencial)
Estructura principal: Línea vertical con brazo diagonal (interruptor).
Lógica de detección: Presenta un óvalo horizontal (toroide) que rodea la línea vertical inferior.
Vínculo de control: A la izquierda del interruptor, hay un cuadrado con una cruz interna conectado mediante una 
línea en ángulo recto que baja hacia el óvalo.
Identificador: están acompañados de la configuración y capacidad, con la corriente diferencial nominal.
Ejemplo: 4x25A 30mA

5. Guardamotor
Envolvente: Un rectángulo horizontal grande que contiene tres líneas verticales paralelas en su interior.
Componentes internos: Cada una de las tres líneas tiene un interruptor con el símbolo de la "escalera" (térmico).
Mecanismo: A la izquierda, fuera de las líneas pero dentro del rectángulo grande, hay un bloque de control (cuadrado con cruz) 
vinculado a los tres interruptores por una línea horizontal.

6. Seccionador
Estructura: Línea vertical interrumpida con brazo diagonal.
Actuador: Encima del brazo diagonal, hay un elemento sólido en forma de martillo o "T" invertida.
Variante con semicírculo: Una versión incluye un pequeño arco o semicírculo unido a la base del "martillo", simulando una manija manual.
Variante con flecha: la otra versión incluye una pequeña flecha unida a la base del "martillo".
identificador: van acompañados del tipo de dispositivo INS y la cantidad de polos y capacidad
Ejemplo: -Q0 INS 4x63A

7. Contactor
Símbolo simple: Una línea diagonal (brazo) que tiene un pequeño gancho o semicírculo en su extremo superior.
Suele estar acompañado por la letra "K" a la derecha. Símbolo de bobina (completo): Un rectángulo vertical (bobina) 
a la izquierda con una línea horizontal que lo conecta a un par de círculos alineados verticalmente (contactos) a la 
derecha. El rectángulo suele tener una "N" roja en su base.

8. Fotocélula
Estructura: Un círculo con la letra "F" en su centro.
Conexiones: Una línea horizontal atraviesa el círculo por el medio.
Indicador de luz: Dos líneas diagonales en forma de "rayo" o zigzag entran al círculo desde el exterior 
(generalmente desde la esquina superior derecha e inferior izquierda).
Identificador: suele estar acompañado de su amperaje 
Ejemplo: Fotocélula 10A

ERRORES CRÍTICOS A EVITAR:
❌ NO cuentes elementos CORTADOS por los bordes del fragmento o incompletos
❌ NO cuentes el MISMO elemento dos veces (si hay dos térmicas con el indicativo TM3, debes contar uno solo)
❌ NO cuentes LÍNEAS DE CONEXIÓN como cables (solo cuenta si hay texto "Xx...")
❌ NO cuentes TEXTOS como "220V", "Cocina", "Baño" (son anotaciones, no materiales)
❌ NO cuentes BARRAS COLECTORAS (líneas gruesas horizontales de soporte)

Ejemplos de análisis:

EJEMPLO 1 - Fragmento simple:
Descripción: Ves 1 pequeño rectángulo atravesado por la mitad por una línea vertical con el signo x3 a su lado, y 3 símbolos que corresponden a los de una térmica.
Respuesta correcta:
{"termicas": 3, "luminaria": 0, "fusibles": 3, "disyuntores": 0, "guardamotor": 0, "seccionador": 0, "contactor": 0, "fotocelula": 0}

EJEMPLO 2 - Cabecera de Tablero General:
Descripción: Ves una línea principal que atraviesa un símbolo con un brazo diagonal y un actuador en forma de martillo sólido en la parte superior etiquetado como -Q0 INS 4x63A. Debajo de este, la línea continúa hacia un símbolo con brazo diagonal, un cuadrado con una cruz a su izquierda y un óvalo horizontal que rodea la línea inferior, 
identificado como 4x40A 30mA. Respuesta correcta:
{"termicas": 0, "luminaria": 0, "fusibles": 0, "disyuntores": 1, "guardamotor": 0, "seccionador": 1, "contactor": 0, "fotocelula": 0}

EJEMPLO 2 - Línea de Iluminación Automatizada:
Descripción: Se observa un símbolo con brazo diagonal que termina en forma de escalera en la base y tiene una pequeña "X" con un guion arriba, con el texto -TM1 2x10A. 
La línea sigue hacia un círculo que contiene una letra F y dos rayos en zigzag en los costados. Finalmente, la línea alimenta a 4 círculos, cada uno con una "X" interna y el signo (R) a su lado. 
Respuesta correcta:
{"termicas": 1, "luminaria": 4, "fusibles": 0, "disyuntores": 0, "guardamotor": 0, "seccionador": 0, "contactor": 0, "fotocelula": 1}

EJEMPLO 3 - Control de Motor Trifásico:
Descripción: Aparece un rectángulo horizontal grande que encierra tres líneas verticales paralelas; cada línea tiene una ruptura en forma de escalera y, a la 
izquierda de todo el conjunto, hay un pequeño cuadrado con una cruz. Inmediatamente debajo, se ven 3 símbolos de brazo diagonal con un pequeño gancho circular 
en el extremo superior, acompañados por la letra K. 
Respuesta correcta:
{"termicas": 0, "luminaria": 0, "fusibles": 0, "disyuntores": 0, "guardamotor": 1, "seccionador": 0, "contactor": 3, "fotocelula": 0}

EJEMPLO 4 - Distribución con Fusibles y Térmicas:
Descripción: Ves 3 rectángulos verticales muy delgados y alargados, cada uno con una línea que los atraviesa por el centro, identificados con el texto 2A x3. 
Debajo de estos, hay 3 símbolos compuestos por una línea vertical, un brazo diagonal con terminación en escalera y una "X" superior, etiquetados como -TM5, -TM6 y -TM7. 
Respuesta correcta:
{"termicas": 3, "luminaria": 0, "fusibles": 3, "disyuntores": 0, "guardamotor": 0, "seccionador": 0, "contactor": 0, "fotocelula": 0}

EJEMPLO 5 - Circuito de Maniobra y Protección:
Descripción: Aparece un símbolo de brazo diagonal con un actuador de martillo que tiene una pequeña flecha en su base, identificado como INS 2x25A. A su lado, 
hay un símbolo de brazo diagonal vinculado a un cuadrado con cruz y un óvalo inferior etiquetado como 30mA. 
El circuito termina en un rectángulo vertical (bobina) a la izquierda conectado a dos círculos con una N roja. 
Respuesta correcta:
{"termicas": 0, "luminaria": 0, "fusibles": 0, "disyuntores": 1, "guardamotor": 0, "seccionador": 1, "contactor": 1, "fotocelula": 0}


PROCESO DE VERIFICACIÓN (hazlo mentalmente antes de responder)
Paso 1: ¿Hay elementos cortados en los bordes? → Ignóralos
Paso 2: Para térmicas, cuenta CADA "TM..." diferente una sola vez, para así NO CONTAR EL MISMO MATERIAL 2 VECES
Paso 3: ¿Los números tienen sentido? (¿20 térmicas en un fragmento pequeño? Revisar)
Paso 4: ¿El JSON está bien formado? Sin comas finales

Generá un JSON que sea una lista de objetos. 
IMPORTANTE: 
El campo 'tipo' debe ser estrictamente un String (texto), no una lista. 
Los campos 'x' e 'y' deben ser Integer (números enteros). 
SIN explicaciones. SIN markdown. Estructura exacta:
[
  {
    "tipo": "nombre_del_material",
    "identificador": "texto_proximo_si_existe",
    "x": valor_entre_0_y_1000,
    "y": valor_entre_0_y_1000
  }
]

Ahora analiza el fragmento adjunto.

"""

def calculate_distance(p1, p2):
    """Calcula la distancia euclidiana entre dos puntos."""
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def deduplicate_detections(detections, threshold=30):
    unique_elements = []
    for new_det in detections:
        is_duplicate = False
        new_id = str(new_det.get('identificador', '')).strip().upper()
        
        for saved_det in unique_elements:
            saved_id = str(saved_det.get('identificador', '')).strip().upper()
            
            # REGLA 1: Si tienen el mismo ID y son el mismo tipo, SON EL MISMO
            if new_id and saved_id and new_id == saved_id and new_det['tipo'] == saved_det['tipo']:
                is_duplicate = True
                break
            
            # REGLA 2: Si no hay ID, usamos la distancia euclidiana
            if new_det['tipo'] == saved_det['tipo']:
                dist = math.sqrt(
                    (new_det['pos_global'][0] - saved_det['pos_global'][0])**2 + 
                    (new_det['pos_global'][1] - saved_det['pos_global'][1])**2
                )
                if dist < threshold:
                    is_duplicate = True
                    break
        
        if not is_duplicate:
            unique_elements.append(new_det)
            
    return unique_elements


async def analizar_esquema_unifilar(pdf_path: str) -> Dict[str, Any]:
    """
    Versión mejorada con deduplicación por coordenadas globales.
    Usa el sistema 0-1000 de Gemini para mapear el tablero completo.
    """
    from unifilar import (
        ConfiguracionProcesamiento, 
        ProcesadorEsquemaUnifilar, 
        FragmentoImagen
    )
    import json
    import logging
    import os
    from datetime import datetime
        
    logger = logging.getLogger(__name__)
    inicio = asyncio.get_event_loop().time()
    
    # ================================================================
    # 0. VARIABLES DE ESTADO GLOBALES
    # ================================================================
    detecciones_globales = []  # Lista maestra para todos los fragmentos
    errores = []
    fragmentos_procesados = 0
    fragmentos_fallidos = 0
    nombre_proyecto = Path(pdf_path).stem
    
    try:
        # 1. VALIDAR PDF (Igual a tu código)
        pdf_path_obj = Path(pdf_path)
        if not pdf_path_obj.exists():
            raise FileNotFoundError(f"PDF no encontrado: {pdf_path}")
        
        # 2. PROCESAR PDF
        config = ConfiguracionProcesamiento(
            dpi=300,
            grilla_filas=2,
            grilla_columnas=2,
            overlap_px=10,  
            corte_superior=0.5,
            formato_salida="PNG"
        )
        
        procesador = ProcesadorEsquemaUnifilar(config)
        fragmentos: List[FragmentoImagen] = await asyncio.to_thread(
            procesador.procesar_pdf,
            str(pdf_path_obj)
        )
        
        carpeta_resultados = Path("resultados") / nombre_proyecto
        
        logger.info(f"Guardando fragmentos en: {carpeta_resultados}")
        await asyncio.to_thread(
            procesador.guardar_en_disco,
            fragmentos,
            str(carpeta_resultados)
        )
                
        # 3. CONFIGURAR GEMINI (Igual a tu código)
        client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
        
        # ================================================================
        # 4. ANALIZAR FRAGMENTOS Y MAPEAR COORDENADAS
        # ================================================================
        
        logger.info("🔍 Analizando fragmentos y mapeando coordenadas...")
        
        for idx, fragmento in enumerate(fragmentos, start=1):
            try:
                contenido = [
                    { "text": PROMPT_ANALISIS },
                    { "inline_data": { "mime_type": "image/png", "data": fragmento.datos } }
                ]
                
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model='gemini-2.0-flash',
                    contents=contenido,
                    config=types.GenerateContentConfig(temperature=0.1)
                )
                
                texto = response.text.strip() # texto limpio 
                
                # Limpieza de markdown JSON
                if "```json" in texto:
                    texto = texto.split("```json")[1].split("```")[0]
                elif "```" in texto:
                    texto = texto.split("```")[1].split("```")[0]
                    
                try:
                    #convierto el texto a lista de python para poder usarlo
                    detecciones_locales = json.loads(texto)
                        
                    if isinstance(detecciones_locales, list):
                        logger.info(f"  ✓ {len(detecciones_locales)} detecciones locales")
                        
                        for det in detecciones_locales:
                            # bbox = (x0, y0, x1, y1)
                            val_x = float(det.get('x', 0))
                            val_y = float(det.get('y', 0))

                            # 3. Guardamos la posición como TUPLA (paréntesis), NO como lista
                            gx = fragmento.x_offset + (val_x * fragmento.ancho / 1000)
                            gy = fragmento.y_offset + (val_y * fragmento.alto / 1000)

                            detecciones_globales.append({
                                "tipo": str(det.get('tipo', 'desconocido')).lower().strip(),
                                "pos_global": (gx, gy) 
                            })
                        fragmentos_procesados += 1
                        logger.info(f"fragmento {idx}: {len(detecciones_locales)} detectados")
                    else:
                        logger.warning(f"Fragmento {idx}: Respuesta no es una lista.")
                
                except json.JSONDecodeError:
                    logger.error(f" ❌ Fragmento {idx}: Error al decodificar JSON")
                
            except Exception as e:
                errores.append(f"Error en fragmento {idx}: {str(e)}")
                fragmentos_fallidos += 1

        # ================================================================
        # 5. DEDUPLICACIÓN Y CONSOLIDACIÓN FINAL
        # ================================================================
        
        logger.info(f"detecciones globales: {detecciones_globales}")
        logger.info("📊 Eliminando duplicados por proximidad espacial...")
        
        # Llamamos a la función de deduplicación que definimos antes
        detecciones_unicas = deduplicate_detections(detecciones_globales, threshold=150) 
        logger.info(f"DETECCIONES ÚNICAS: {detecciones_unicas}")
        # Mapeo de categorías para el conteo final
        categorias = [
            "termica", "luminaria", "fusibles", "disyuntor", 
            "guardamotor", "seccionador", "contactor", "fotocelula"
        ]
        
        conteo_final = {cat: 0 for cat in categorias}
        for det in detecciones_unicas:
            tipo = det['tipo']
            if tipo in conteo_final:
                conteo_final[tipo] += 1
            # Manejo de plurales o variaciones comunes
            elif tipo == "termicas": conteo_final["termica"] += 1
            elif tipo == "disyuntores": conteo_final["disyuntor"] += 1

        # ================================================================
        # 6. RESULTADO FINAL
        # ================================================================
        
        tiempo_total = asyncio.get_event_loop().time() - inicio
        total_fragmentos = len(fragmentos)
        logger.info(f"✅ {total_fragmentos} fragmentos extraídos")
        
        return {
            "status": "success",
            "proyecto": nombre_proyecto,
            "conteo_materiales": conteo_final,
            "metadatos": {
                "total_detecciones_crudas": len(detecciones_globales),
                "total_detecciones_unicas": len(detecciones_unicas),
                "fragmentos_procesados": fragmentos_procesados,
                "tiempo_total_segundos": round(tiempo_total, 2),
                "total_fragmentos": total_fragmentos,
                "timestamp": datetime.now().isoformat(),
            },
            "errores": errores
        }

    except Exception as e:
        logger.error(f"❌ Error crítico: {e}", exc_info=True)
        return {"status": "error", "errores": [str(e)]}

async def iniciar_recoleccion_interactiva(chat_id: int):
    """
    Inicia el flujo de recolección interactiva de datos
    Esta función NO ejecuta el dimensionamiento, solo inicia el flujo en Telegram
    """
    if chat_id is None:
        return "❌ Error: chat_id es None"
    
    estado = obtener_estado(chat_id)
    
    logger.info(f"🔄 Iniciando recolección interactiva para chat_id={chat_id}")
    logger.info(f"estados actuales: {estado}")
    if estado.en_proceso:
        return "⚠️ Ya hay un proceso de recolección en curso. Por favor, complétalo primero."
    
    try:
        # Verificar que el callback esté registrado
        if not _callback_recoleccion:
            return "❌ Error: Sistema de recolección no inicializado. Contacta al administrador."
        
        # Inicializar estado
        estado.en_proceso = True
        estado.datos_recolectados = None
        
        # Llamar al callback del bot para iniciar la recolección
        mensaje = "Vamos a dimensionar tu tablero eléctrico. Te haré algunas preguntas:"
        
        _callback_recoleccion(  # ejecuto la funcion de iniciar_recoleccion
            mensaje=mensaje,
            tipo='iniciar_flujo_recoleccion',
            chat_id=chat_id
        )
        
        logger.info(f"✅ Recolección iniciada")
        
        return """✅ Proceso de recolección iniciado.

    Por favor, responde las preguntas que aparecerán en los botones de Telegram.
    Una vez completes todos los datos, generaré el dimensionamiento automáticamente."""
            
    except Exception as e:
        logger.exception("Error iniciando recolección")
        estado.en_proceso = False
        return f"❌ Error al iniciar recolección: {str(e)}"

async def _ejecutar_dimensionamiento_con_datos(datos: dict) -> str:
    """
    Ejecuta el dimensionamiento con los datos ya recolectados
    llamada automáticamente cuando se completa la recolección
    """
    # Obtener chat_id desde los datos (fue pasado desde bot.py)
    chat_id_actual = datos.get('chat_id')
    
    if not chat_id_actual:
        return "❌ Error: chat_id no disponible"

    try:
        config_input = datos.get('config_input')
        materiales_input = datos.get('materiales_input')
        print("------------------ MATERIALES INPUT ------------------", materiales_input)
        
        if not config_input or not materiales_input:
            return "❌ Error: Datos incompletos recibidos"
        
        # Convertir a objetos
        config = ConfiguracionInput(**config_input)
        materiales = [MaterialInput(**m) for m in materiales_input]
        
        # Cargar datos
        datos_excel = cargar_datos()
        procesador = ProcesadorMateriales(datos_excel)
        
        # Procesar seleccionador
        mat_sel, tipo_tablero_str, ancho_sel = procesador.procesar_seleccionador(
            config.seleccionador_ref
        )
        
        if not mat_sel:
            return f"❌ Error: Seleccionador '{config.seleccionador_ref}' no encontrado"
        
        # Convertir materiales a formato interno
        anchos_dif = []
        anchos_term = []
        listado_materiales = [mat_sel]
        
        for mat in materiales:
            if mat.categoria == "DIF":
                df_dif = datos_excel['diferencial']
                sup_db = "SI" if mat.superinmunizado else "NO"
                
                match = df_dif[
                    (df_dif['CANT POLOS'].astype(str) == mat.polos) &
                    (df_dif['CORRIENTE'].astype(str) == mat.amperaje) &
                    (df_dif['FAMILIA'].astype(str) == mat.familia) &
                    (df_dif['SUPERINMUNIZADO'].astype(str) == sup_db)
                ]

                
                if not match.empty:
                    res = match.iloc[0]
                    ancho = float(res['MEDIDA'])
                    anchos_dif.extend([ancho] * mat.cantidad)
                    
                    listado_materiales.append(Material(
                        codigo=str(res['CODIGO']),
                        descripcion=str(res['DESCRIPCION']),
                        cantidad=mat.cantidad,
                        categoria="DIFERENCIAL",
                        ancho_mm=ancho
                    ))
            
            else:  # TERM (ahora usa TERM en lugar de TERMICA para que coincida con bot.py)
                df_term = datos_excel['termicas']
                match = df_term[
                    (df_term['CANT POLOS'].astype(str) == mat.polos) &
                    (df_term['CORRIENTE'].astype(str) == mat.amperaje) &
                    (df_term['FAMILIA'].astype(str) == mat.familia)
                ]
                
                if not match.empty:
                    res = match.iloc[0]
                    ancho = float(res['MEDIDA'])
                    anchos_term.extend([ancho] * mat.cantidad)
                    
                    listado_materiales.append(Material(
                        codigo=str(res['CODIGO']),
                        descripcion=str(res['DESCRIPCION']),
                        cantidad=mat.cantidad,
                        categoria="TERMICA",
                        ancho_mm=ancho
                    ))
        
        # Calcular rieles y seleccionar gabinete
        config_tablero = ConfiguracionTablero(
            seleccionador_ref=config.seleccionador_ref,
            tiene_borneras=config.tiene_borneras,
            aplicar_reserva=config.aplicar_reserva,
            tipo_contrafrente=config.tipo_contrafrente # EL CONTRAFRENTE TRAE EL CÓDIGO DEL PRODUCTO ASOCIADO
        )
        
        calculador = CalculadorRieles(config_tablero)
        selector = SelectorGabinete(datos_excel['envolventes'])
        tipo_tablero = TipoTablero(tipo_tablero_str)
        
        gabinete = selector.seleccionar_gabinete(
            tipo_tablero,
            calculador,
            ancho_sel,
            anchos_dif,
            anchos_term
        )
        
        if not gabinete:
            return "❌ No se encontró un gabinete compatible"
        
        # Calcular rieles usados
        rieles_usados = calculador.calcular_rieles_necesarios(
            gabinete.largo_riel,
            ancho_sel,
            anchos_dif,
            anchos_term
        )
        
        # Agregar gabinete
        listado_materiales.append(Material(
            codigo=gabinete.codigo,
            descripcion=gabinete.descripcion,
            cantidad=1,
            categoria="GABINETE"
        ))
        
        # Agregar accesorios
        accesorios = procesador.procesar_accesorios(gabinete, config.tipo_contrafrente)
        listado_materiales.extend(accesorios)
        
        # Crear hoja de resumen ANTES de exportar (así cuenta los materiales finales)
        hoja_resumen = crear_hoja_resumen(gabinete, config, rieles_usados, listado_materiales)
        
        # Exportar a Excel con la hoja de resumen
        nombre_archivo = exportar_a_excel(
            gabinete=gabinete,
            listado_materiales=listado_materiales,
            config=config,
            rieles_usados=rieles_usados,
            anchos_dif=anchos_dif,
            anchos_term=anchos_term,
            materiales_input=materiales_input,
            hoja_resumen=hoja_resumen
        )
        
        # Formatear respuesta
        resultado = f"""✅ DIMENSIONAMIENTO COMPLETADO

        📦 GABINETE: {gabinete.descripcion}
        Código: {gabinete.codigo}
        Dimensiones: {gabinete.ancho}x{gabinete.alto}x{gabinete.profundidad} mm
        Rieles: {rieles_usados}/{gabinete.cantidad_columnas}

        📋 MATERIALES ({len(listado_materiales)} items):
        """
        
        # Agrupar por categoría
        categorias = {}
        for mat in listado_materiales:
            if mat.categoria not in categorias:
                categorias[mat.categoria] = []
            categorias[mat.categoria].append(mat)
        
        for cat, items in categorias.items():
            resultado += f"\n{cat}:\n"
            for mat in items:
                resultado += f"  • [{mat.codigo}] {mat.descripcion} x{mat.cantidad}\n"
        
        resultado += f"\n💾 ARCHIVO GENERADO:\n   {nombre_archivo}\n"
        
        # Enviar archivo por Telegram
        if _callback_recoleccion:
            excel_bytes = exportar_y_obtener_bytes(
                gabinete=gabinete,
                listado_materiales=listado_materiales,
                config=config,
                rieles_usados=rieles_usados,
                anchos_dif=anchos_dif,
                anchos_term=anchos_term,
                materiales_input=materiales_input
            )
            
            _callback_recoleccion(
                mensaje=resultado,
                tipo='enviar_excel',
                chat_id=chat_id_actual,
                archivo_bytes=excel_bytes,
                nombre_archivo=f"Tablero_{gabinete.codigo}.xlsx"
            )
        
        # Resetear estado global después de completar exitosamente
        resetear_estado_recoleccion(chat_id_actual)
        
        return resultado
            
    except Exception as e:
        logger.exception("Error en dimensionamiento")
        # Resetear estado global también en caso de error
        resetear_estado_recoleccion(chat_id_actual)
        return f"❌ Error: {str(e)}"


def exportar_a_excel(
    gabinete,
    listado_materiales: list,
    config: ConfiguracionInput,
    rieles_usados: int,
    anchos_dif: list,
    anchos_term: list,
    materiales_input: list,
    hoja_resumen: pd.DataFrame = None
) -> str:
    """
    Exporta los resultados del dimensionamiento a un archivo Excel con múltiples hojas
    
    Returns:
        str: Ruta del archivo generado
    """
    
    nombre_archivo_base = f"Tablero_{gabinete.codigo}.xlsx"
        
    solo_nombre = os.path.basename(nombre_archivo_base)
    ruta_final = os.path.join("resultados", solo_nombre)
        
    logger.info(f"📝 Intentando escribir Excel en: {ruta_final}")
        
    try:
        # Crear escritor de Excel
        with pd.ExcelWriter(ruta_final, engine='openpyxl') as writer:
            
            # === HOJA 1: RESUMEN DEL PROYECTO ===
            # Usar la hoja de resumen precalculada si se proporciona
            if hoja_resumen is not None:
                hoja_resumen.to_excel(writer, sheet_name='Resumen', index=False)
            else:
                # Fallback: crear en el momento (pero esto no debería pasar)
                df_resumen = crear_hoja_resumen(
                    gabinete, config, rieles_usados, 
                    listado_materiales
                )
                df_resumen.to_excel(writer, sheet_name='Resumen', index=False)
            
            # === HOJA 2: LISTADO DE MATERIALES ===
            df_materiales = crear_hoja_materiales(listado_materiales)
            df_materiales.to_excel(writer, sheet_name='Listado_Materiales', index=False)
            
            # === HOJA 3: MATERIALES POR CATEGORÍA ===
            df_por_categoria = crear_hoja_por_categoria(listado_materiales)
            df_por_categoria.to_excel(writer, sheet_name='Por_Categoria', index=False)
            
            # === HOJA 4: DETALLES TÉCNICOS ===
            df_tecnicos = crear_hoja_detalles_tecnicos(
                config, rieles_usados, anchos_dif, anchos_term, gabinete
            )
            df_tecnicos.to_excel(writer, sheet_name='Detalles_Tecnicos', index=False)
            
            # === HOJA 5: MATERIALES SOLICITADOS (ENTRADA) ===
            df_entrada = pd.DataFrame(materiales_input)
            df_entrada.to_excel(writer, sheet_name='Materiales_Solicitados', index=False)
        
        logger.info(f"✅ Excel generado: {ruta_final}")
        return str(ruta_final)
        
    except Exception as e:
        logger.error(f"❌ Error generando Excel: {e}")
        raise 


def crear_hoja_resumen(
    gabinete,
    config: ConfiguracionInput,
    rieles_usados: int,
    listado_materiales: list
) -> pd.DataFrame:
    """Crea DataFrame con resumen del proyecto, contando materiales del listado final"""
    
    # Contar materiales por categoría desde el listado final
    total_dif = sum(1 for mat in listado_materiales if mat.categoria == "DIFERENCIAL")
    total_term = sum(1 for mat in listado_materiales if mat.categoria == "TERMICA")
    total_materiales = len(listado_materiales)
    
    datos_resumen = {
        'CAMPO': [
            'FECHA',
            'HORA',
            '',
            'GABINETE SELECCIONADO',
            'Código',
            'Tipo',
            'Dimensiones (mm)',
            'Largo de Riel (mm)',
            'Rieles Utilizados',
            'Rieles Disponibles',
            '',
            'CONFIGURACIÓN',
            'Seleccionador',
            'Borneras',
            'Reserva Aplicada',
            'Tipo Contrafrente',
            '',
            'RESUMEN DE MATERIALES',
            'Diferenciales',
            'Térmicas',
            'Total Items',
        ],
        'VALOR': [
            datetime.now().strftime("%Y-%m-%d"),
            datetime.now().strftime("%H:%M:%S"),
            '',
            gabinete.descripcion,
            gabinete.codigo,
            gabinete.tipo,
            f"{gabinete.ancho}x{gabinete.alto}x{gabinete.profundidad}",
            gabinete.largo_riel,
            rieles_usados,
            gabinete.cantidad_columnas,
            '',
            '',
            config.seleccionador_ref,
            'Sí' if config.tiene_borneras else 'No',
            'Sí' if config.aplicar_reserva else 'No',
            config.tipo_contrafrente,
            '',
            '',
            total_dif,
            total_term,
            total_materiales,
        ]
    }
    
    return pd.DataFrame(datos_resumen)


def crear_hoja_materiales(listado_materiales: list) -> pd.DataFrame:
    """Crea DataFrame con listado completo de materiales"""
    
    datos = []
    for idx, mat in enumerate(listado_materiales, 1):
        datos.append({
            'ITEM': idx,
            'CODIGO': mat.codigo,
            'DESCRIPCION': mat.descripcion,
            'CANTIDAD': mat.cantidad,
            'CATEGORIA': mat.categoria,
            'ANCHO_MM': mat.ancho_mm if mat.ancho_mm > 0 else '-'
        })
    
    return pd.DataFrame(datos)


def crear_hoja_por_categoria(listado_materiales: list) -> pd.DataFrame:
    """Crea DataFrame agrupado por categoría"""
    
    # Agrupar por categoría
    categorias = {}
    for mat in listado_materiales:
        if mat.categoria not in categorias:
            categorias[mat.categoria] = []
        categorias[mat.categoria].append(mat)
    
    # Crear datos para el DataFrame
    datos = []
    for categoria, items in categorias.items():
        # Encabezado de categoría
        datos.append({
            'CATEGORIA': categoria,
            'CODIGO': '',
            'DESCRIPCION': '',
            'CANTIDAD': '',
            'SUBTOTAL_ITEMS': len(items)
        })
        
        # Items de la categoría
        for mat in items:
            datos.append({
                'CATEGORIA': '',
                'CODIGO': mat.codigo,
                'DESCRIPCION': mat.descripcion,
                'CANTIDAD': mat.cantidad,
                'SUBTOTAL_ITEMS': ''
            })
        
        # Línea en blanco
        datos.append({
            'CATEGORIA': '',
            'CODIGO': '',
            'DESCRIPCION': '',
            'CANTIDAD': '',
            'SUBTOTAL_ITEMS': ''
        })
    
    return pd.DataFrame(datos)


def crear_hoja_detalles_tecnicos(
    config: ConfiguracionInput,
    rieles_usados: int,
    anchos_dif: list,
    anchos_term: list,
    gabinete
) -> pd.DataFrame:
    """Crea DataFrame con detalles técnicos del dimensionamiento"""
    
    # estadísticas
    ocupacion_dif = sum(anchos_dif) if anchos_dif else 0
    ocupacion_term = sum(anchos_term) if anchos_term else 0
    ocupacion_total = ocupacion_dif + ocupacion_term
    capacidad_total = rieles_usados * gabinete.largo_riel
    espacio_libre = capacidad_total - ocupacion_total
    porcentaje_ocupacion = (ocupacion_total / capacidad_total * 100) if capacidad_total > 0 else 0
    
    datos_tecnicos = {
        'PARAMETRO': [
            'OCUPACIÓN DE RIELES',
            'Largo de riel (mm)',
            'Rieles utilizados',
            'Capacidad total (mm)',
            '',
            'Ocupación diferenciales (mm)',
            'Cantidad diferenciales',
            'Promedio por diferencial (mm)',
            '',
            'Ocupación térmicas (mm)',
            'Cantidad térmicas',
            'Promedio por térmica (mm)',
            '',
            'TOTALES',
            'Ocupación total (mm)',
            'Espacio libre (mm)',
            'Porcentaje ocupación (%)',
            'Porcentaje libre (%)',
            '',
            'VALIDACIONES',
            'Reserva del 20% aplicada',
            'Cumple con reserva',
            'Rieles dentro de límite',
        ],
        'VALOR': [
            '',
            gabinete.largo_riel,
            rieles_usados,
            capacidad_total,
            '',
            round(ocupacion_dif, 2),
            len(anchos_dif),
            round(ocupacion_dif / len(anchos_dif), 2) if anchos_dif else 0,
            '',
            round(ocupacion_term, 2),
            len(anchos_term),
            round(ocupacion_term / len(anchos_term), 2) if anchos_term else 0,
            '',
            '',
            round(ocupacion_total, 2),
            round(espacio_libre, 2),
            round(porcentaje_ocupacion, 2),
            round(100 - porcentaje_ocupacion, 2),
            '',
            '',
            'Sí' if config.aplicar_reserva else 'No',
            'Sí' if (100 - porcentaje_ocupacion) >= 15 else 'No',
            'Sí' if rieles_usados <= gabinete.cantidad_columnas else 'No',
        ]
    }
    
    return pd.DataFrame(datos_tecnicos)


# === FUNCIÓN ALTERNATIVA: EXPORTAR A ARCHIVO SIMPLE ===

def exportar_a_excel_simple(
    gabinete,
    listado_materiales: list,
    config: ConfiguracionInput
) -> str:
    """
    Versión simplificada: Exporta solo el listado de materiales
    Útil si solo necesitas una tabla básica
    """
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivo = OUTPUT_DIR / f"Materiales_{gabinete.codigo}_{timestamp}.xlsx"
    
    try:
        # Convertir lista de objetos Material a DataFrame
        df = pd.DataFrame([
            {
                'Código': mat.codigo,
                'Descripción': mat.descripcion,
                'Cantidad': mat.cantidad,
                'Categoría': mat.categoria
            }
            for mat in listado_materiales
        ])
        
        # Guardar
        df.to_excel(nombre_archivo, index=False, sheet_name='Materiales')
        
        logger.info(f"✅ Excel simple generado: {nombre_archivo}")
        return str(nombre_archivo)
        
    except Exception as e:
        logger.error(f"❌ Error generando Excel simple: {e}")
        raise

# === FUNCIÓN PARA TELEGRAM: ENVIAR EXCEL COMO ADJUNTO ===

def exportar_y_obtener_bytes(
    gabinete,
    listado_materiales: list,
    config: ConfiguracionInput,
    rieles_usados: int,
    anchos_dif: list,
    anchos_term: list,
    materiales_input: list
) -> bytes:
    """
    Genera el Excel y retorna los bytes para enviarlo por Telegram
    sin guardar en disco
    """

    try:
        # Crear buffer en memoria
        buffer = BytesIO()
        
        # Crear escritor de Excel en memoria
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            
            # Crear todas las hojas usando el listado final de materiales
            df_resumen = crear_hoja_resumen(
                gabinete, config, rieles_usados, 
                listado_materiales
            )
            df_resumen.to_excel(writer, sheet_name='Resumen', index=False)
            
            df_materiales = crear_hoja_materiales(listado_materiales)
            df_materiales.to_excel(writer, sheet_name='Listado_Materiales', index=False)
            
            df_por_categoria = crear_hoja_por_categoria(listado_materiales)
            df_por_categoria.to_excel(writer, sheet_name='Por_Categoria', index=False)
            
            df_tecnicos = crear_hoja_detalles_tecnicos(
                config, rieles_usados, anchos_dif, anchos_term, gabinete
            )
            df_tecnicos.to_excel(writer, sheet_name='Detalles_Tecnicos', index=False)
            
            df_entrada = pd.DataFrame(materiales_input)
            df_entrada.to_excel(writer, sheet_name='Materiales_Solicitados', index=False)
        
        # Obtener bytes del buffer
        buffer.seek(0)
        return buffer.getvalue()
        
    except Exception as e:
        logger.error(f"❌ Error generando Excel en memoria: {e}")
        raise

def buscar_seleccionador(referencia: str) -> str:
    """Busca un seleccionador"""
    
    try:
        datos = cargar_datos()
        procesador = ProcesadorMateriales(datos)
        
        mat_sel, tipo_tablero, ancho = procesador.procesar_seleccionador(referencia)
        
        if not mat_sel:
            return f"❌ Seleccionador '{referencia}' no encontrado"
        
        return f"""✅ SELECCIONADOR ENCONTRADO

Código: {mat_sel.codigo}
Descripción: {mat_sel.descripcion}
Tipo: {tipo_tablero}
Ancho: {ancho} mm"""
        
    except Exception as e:
        return f"❌ Error: {str(e)}"


def listar_gabinetes_disponibles(tipo: str, ancho_minimo: float = 0, alto_minimo: float = 0) -> str:
    """Lista gabinetes disponibles filtrados con todos sus detalles técnicos"""
    
    try:
        # 1. Cargar datos (usando la función de caché con Pandas)
        datos = cargar_datos()
        df = datos['envolventes'].copy()

        # Limpieza preventiva de nombres de columnas (asegura coincidencia)
        df.columns = [str(c).strip().upper() for c in df.columns]
   
        # 2. Aplicar filtros
        if tipo.upper() != "TODOS":
            df = df[df['TIPO'] == tipo.upper()]
        
        if ancho_minimo > 0:
            df = df[df['ANCHO'] >= ancho_minimo]
        
        if alto_minimo > 0:
            df = df[df['ALTO'] >= alto_minimo]
        
        # 3. Ordenar resultados
        df = df.sort_values(['TIPO', 'ANCHO', 'ALTO'])
        
        # 4. Verificar si hay resultados
        if df.empty:
            return f"❌ No se encontraron gabinetes de tipo '{tipo}' con las dimensiones especificadas."
        
        # 5. Construir el string de salida con todas las columnas solicitadas
        resultado = f"📦 GABINETES ENCONTRADOS: {len(df)}\n"
        resultado += "="*40 + "\n\n"
        
        for _, row in df.iterrows():
            resultado += f"🔹 CÓDIGO: {row['CODIGO']}\n"
            resultado += f"   Descripción: {row['DESCRIPCION']}\n"
            #resultado += f"   Dimensiones: {row['ANCHO']} x {row['ALTO']} x {row['PROFUNDIDAD']} mm\n"
            #resultado += f"   Tipo: {row['TIPO']} | Fabricante: {row['FABRICANTE']}\n"
            #resultado += f"   Capacidad: {row['CANTIDAD DE COLUMNAS']} rieles | Largo Riel: {row['LARGO_RIEL']} mm\n"
            resultado += "-"*30 + "\n"
        print(resultado)
        return resultado
        
    except Exception as e:
        logger.error(f"Error en listar_gabinetes: {e}")
        return f"❌ Error al procesar la lista: {str(e)}"


def validar_configuracion(configuracion: dict, materiales: list) -> str:
    """Valida configuración"""
    
    try:
        datos = cargar_datos()
        procesador = ProcesadorMateriales(datos)
        
        # Validar seleccionador
        mat_sel, tipo_tablero, ancho_sel = procesador.procesar_seleccionador(
            configuracion["seleccionador_ref"]
        )
        
        if not mat_sel:
            return f"❌ Seleccionador '{configuracion['seleccionador_ref']}' no existe"
        
        # Validar materiales
        materiales_validos = 0
        materiales_invalidos = []
        
        for mat in materiales:
            if mat['categoria'] == 'DIF':
                df = datos['diferencial']
                sup = "SI" if mat.get('superinmunizado', False) else "NO"
                match = df[
                    (df['CANT POLOS'].astype(str) == mat['polos']) &
                    (df['CORRIENTE'].astype(str) == mat['amperaje']) &
                    (df['FAMILIA'].astype(str) == mat['familia']) &
                    (df['SUPERINMUNIZADO'].astype(str) == sup)
                ]
            else:
                df = datos['termicas']
                match = df[
                    (df['CANT POLOS'].astype(str) == mat['polos']) &
                    (df['CORRIENTE'].astype(str) == mat['amperaje']) &
                    (df['FAMILIA'].astype(str) == mat['familia'])
                ]
            
            if match.empty:
                materiales_invalidos.append(f"{mat['categoria']} {mat['polos']} {mat['amperaje']}A")
            else:
                materiales_validos += mat['cantidad']
        
        if materiales_invalidos:
            return f"⚠️ Materiales no encontrados:\n" + "\n".join(f"  - {m}" for m in materiales_invalidos)
        
        return f"✅ Configuración válida. {materiales_validos} dispositivos."
        
    except Exception as e:
        return f"❌ Error: {str(e)}"

# Registrar funciones en el mapa
FUNCTION_MAP = {
    "iniciar_recoleccion_interactiva": iniciar_recoleccion_interactiva,
    "buscar_seleccionador": buscar_seleccionador,
    "listar_gabinetes_disponibles": listar_gabinetes_disponibles,
    "validar_configuracion": validar_configuracion,
    "analizar_esquema_unifilar": analizar_esquema_unifilar
}


# === FUNCIÓN PRINCIPAL ===

load_dotenv(dotenv_path=".env")

try:
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    logger.info("✅ Cliente Gemini configurado")
except Exception as e:
    logger.error(f"❌ Error al configurar el cliente: {e}")
    client = None


async def actualizar_datos(
    config_updates: dict = None,
    materiales_agregar: list = None,
    materiales_eliminar_indices: list = None,
    descripcion_cambios: str = None
) -> str:
    """
    Actualiza los datos de configuración y materiales en edición.
    Permite modificar selectivamente la config y la lista de materiales.
    """
    try:
        global datos_en_edicion
        
        # Obtener datos actuales
        config = datos_en_edicion.get("config", {})
        materiales = datos_en_edicion.get("materiales", [])
        
        # Actualizar configuración
        if config_updates:
            config.update(config_updates)
            logger.info(f"📝 Configuración actualizada: {config_updates}")
        
        # Agregar materiales
        if materiales_agregar:
            for mat in materiales_agregar:
                materiales.append(mat)
            logger.info(f"➕ {len(materiales_agregar)} material(es) agregado(s)")
        
        # Eliminar materiales (en orden inverso para no afectar índices)
        if materiales_eliminar_indices:
            indices_ordenados = sorted(set(materiales_eliminar_indices), reverse=True)
            for idx in indices_ordenados:
                if 0 <= idx < len(materiales):
                    materiales.pop(idx)
            logger.info(f"❌ {len(indices_ordenados)} material(es) eliminado(s)")
        
        # Guardar datos actualizados
        datos_en_edicion["config"] = config
        datos_en_edicion["materiales"] = materiales
        
        # Construir respuesta legible
        resumen = "✅ DATOS ACTUALIZADOS CORRECTAMENTE\n\n"
        
        if descripcion_cambios:
            resumen += f"📝 Cambios: {descripcion_cambios}\n\n"
        
        # Mostrar configuración actual
        resumen += "📋 CONFIGURACIÓN ACTUAL:\n"
        resumen += f"  🔧 Seleccionador: {config.get('seleccionador_ref', '?')}\n"
        resumen += f"  🗄️ Gabinete: {config.get('tipo_gabinete', '?')}\n"
        resumen += f"  🔌 Borneras: {'Sí' if config.get('tiene_borneras') else 'No'}\n"
        resumen += f"  📦 Reserva: {'Sí' if config.get('aplicar_reserva') else 'No'}\n"
        resumen += f"  🚪 Contrafrente: {config.get('tipo_contrafrente', '?')}\n\n"
        
        # Mostrar materiales actuales
        resumen += f"📦 MATERIALES ({len(materiales)}):\n"
        for i, mat in enumerate(materiales, 1):
            sup = " (Superinmunizado)" if mat.get("superinmunizado") else ""
            resumen += f"  {i}. {mat.get('cantidad', '?')}u {mat.get('categoria', '?')} {mat.get('polos', '?')} {mat.get('amperaje', '?')} {mat.get('familia', '?')}{sup}\n"
        
        return resumen
        
    except Exception as e:
        logger.exception("❌ Error al actualizar datos")
        return f"❌ Error al actualizar datos: {str(e)}"

async def run_mcp(question:str, chat_id_original=None) -> str:

    """
    Procesa una pregunta usando Gemini con function calling
    """
    
    if not client:
        return "❌ Cliente Gemini no configurado"
    
    try:
        logger.info(f"📨 Pregunta: {question}")
        
        # Obtener las declaraciones de tools
        tools = get_tools_declarations()
        
        # Primera llamada a Gemini
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=question,
            config=types.GenerateContentConfig( # indicarle que no responda con texto y haga solo function calls reduce el consumo de tokens
                system_instruction="""Eres un experto en tableros eléctricos.
    IMPORTANTE: Si el usuario quiere dimensionar, armar o crear un tablero, 
    NO respondas con texto. Llama INMEDIATAMENTE a la herramienta 
    'iniciar_recoleccion_interactiva' sin dar explicaciones previas.
    Tu prioridad es activar el asistente interactivo.""",
                tools=tools,
                temperature=0.1
            )
        )
        
        logger.info("✅ Respuesta recibida de Gemini")
        
        # Verificar si hay function calls
        if not response.candidates:
            return "❌ No se recibió respuesta de Gemini"
        
        candidate = response.candidates[0]
        
        if not candidate.content or not candidate.content.parts:
            return "❌ Respuesta vacía de Gemini"
        
        # Procesar las partes de la respuesta
        for part in candidate.content.parts:
            # Si es texto directo
            if part.text:
                return part.text
            
            # Si es una llamada a función
            if part.function_call:
                func_call = part.function_call
                func_name = func_call.name
                func_args = dict(func_call.args)
                
                logger.info(f"🔧 Llamando función: {func_name}")
                logger.info(f"📋 Argumentos: {func_args}")
                
                # Ejecutar la función
                if func_name in FUNCTION_MAP:
                    func = FUNCTION_MAP[func_name]
                    
                    # Llamar la función con los argumentos correctos
                    if func_name == "iniciar_recoleccion_interactiva":
                        result = await func(chat_id=chat_id_original)
                    elif func_name == "buscar_seleccionador":
                        result = func(referencia=func_args.get("referencia"))
                    elif func_name == "listar_gabinetes_disponibles":
                        result = func(
                            tipo=func_args.get("tipo"),
                            ancho_minimo=func_args.get("ancho_minimo", 0),
                            alto_minimo=func_args.get("alto_minimo", 0)
                        )
                    elif func_name == "validar_configuracion":
                        result = func(
                            configuracion=func_args.get("configuracion"),
                            materiales=func_args.get("materiales")
                        )
                    elif func_name == "actualizar_datos":
                        result = await func(
                            config_updates=func_args.get("config_updates"),
                            materiales_agregar=func_args.get("materiales_agregar"),
                            materiales_eliminar_indices=func_args.get("materiales_eliminar_indices"),
                            descripcion_cambios=func_args.get("descripcion_cambios")
                        )
                    elif func_name == "analizar_esquema_unifilar":
                        result = await func(
                            pdf_path = func_args.get("pdf_path"),
                        )
                    else:
                        result = "❌ Función no implementada"
                    
                        if asyncio.iscoroutine(result):
                            result = await result
                        
                    return result
                    
                else:
                    return f"❌ Función '{func_name}' no encontrada"
        
        return "❌ No se pudo procesar la respuesta"
        
    except Exception as e:
        logger.exception("❌ Error en run_mcp")
        return f"❌ Error: {type(e).__name__}: {str(e)}"


async def run_orquestador(question: str, chat_id_original=None) -> str:
    """
    Punto de entrada desde el bot de Telegram
    """
    return await run_mcp(question, chat_id_original=chat_id_original)


# === ASIGNAR FUNCIONES AL MAPA ===
FUNCTION_MAP["iniciar_recoleccion_interactiva"] = iniciar_recoleccion_interactiva
FUNCTION_MAP["buscar_seleccionador"] = buscar_seleccionador
FUNCTION_MAP["listar_gabinetes_disponibles"] = listar_gabinetes_disponibles
FUNCTION_MAP["validar_configuracion"] = validar_configuracion
FUNCTION_MAP["actualizar_datos"] = actualizar_datos
FUNCTION_MAP["analizar_esquema_unifilar"] = analizar_esquema_unifilar


# if __name__ == "__main__":
    
