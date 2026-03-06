import asyncio
import logging
import datetime
from datetime import datetime
import pandas as pd
from io import BytesIO
from typing import List, Dict, Any
import math
import copy
import tempfile

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
}

# === IMPLEMENTACIÓN DE FUNCIONES ===

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
    
    """
    
    temp_dir = Path(tempfile.gettempdir()) / "cotizabot_resultados"
                    
    try:
        # Crear escritor de Excel
        temp_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(temp_dir, 0o777)
    except Exception as e:
        logger.warning("no se pudo crear carpeta temporal")
        temp_dir = Path(tempfile.gettempdir())  # fallback a temp sin subcarpeta
    
    nombre_archivo_base = f"Tablero_{gabinete.codigo}.xlsx"
    solo_nombre = os.path.basename(nombre_archivo_base)
    # Reemplazamos espacios por guiones para evitar problemas de rutas en Linux
    solo_nombre = solo_nombre.replace(" ", "_")
    
    ruta_final = temp_dir / solo_nombre
    
    logger.info(f"📝 Intentando escribir Excel en ruta segura: {ruta_final}")
    
    try:
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
        
        logger.info(f"✅ Excel generado exitosamente en: {ruta_final}")
        return str(ruta_final)
        
    except Exception as e:
        logger.error(f"❌ Error generando Excel en {ruta_final}: {e}")
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

# if __name__ == "__main__":
    
