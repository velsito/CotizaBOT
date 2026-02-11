import os
import logging
from dotenv import load_dotenv
import asyncio
from pathlib import Path
import http.server
import socketserver
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from servidor_mcp import registrar_callback_recoleccion
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
    ApplicationBuilder
)

EXCEL_OUTPUT_DIR = os.getenv("EXCEL_OUTPUT", "./resultados/")

load_dotenv(dotenv_path=".env")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Falta la variable de entorno TELEGRAM_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)



###
class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    
    # Esto es para que el log no se llene de basura de pings
    def log_message(self, format, *args):
        return

def run_health_server():
    # Render nos obliga a usar el puerto que ellos digan
    port = int(os.environ.get("PORT", 10000))
    with socketserver.TCPServer(("0.0.0.0", port), HealthCheckHandler) as httpd:
        print(f"🌍 Servidor de Health Check corriendo en el puerto {port}")
        httpd.serve_forever()
###



# Almacenamiento persistente de última configuración por chat_id
ultima_config_storage = {} # lo uso para almacenar los inputs de config y materiales que se usan en el dimensionamiento

(
    SELECCIONADOR_REF,
    TIPO_GABINETE,
    TIENE_BORNERAS,
    APLICAR_RESERVA,
    TIPO_CONTRAFRENTE,
    MENU_MATERIALES,
    CATEGORIA,
    CANTIDAD,
    POLOS,
    AMPERAJE,
    FAMILIA,
    SUPERINMUNIZADO,
    CONFIRMACION_FINAL,
) = range(13)

bot_application: Application = None

async def iniciar_recoleccion_datos(update: Update = None, context: ContextTypes.DEFAULT_TYPE = None, chat_id: int = None):
    """
    Función llamada por el modelo MCP cuando invoca la tool dimensionar_tablero_completo.
    Inicia el flujo interactivo de recolección de datos
    
    Args:
        update: (Opcional) Objeto Update de Telegram para acceder a información del mensaje
        context: (Opcional) Contexto del usuario para almacenar datos
        chat_id: (Opcional) ID del chat, utilizado cuando se llama desde el callback MCP
    """

    # Obtener chat_id desde diferentes fuentes
    if chat_id is not None:
        chat_id_actual = chat_id
    elif update and hasattr(update, 'effective_chat') and update.effective_chat:
        chat_id_actual = update.effective_chat.id
    else:
        chat_id_actual = None
    
    keyboard = [
        [InlineKeyboardButton("3Px40A", callback_data="sel_3Px40A"),
         InlineKeyboardButton("4Px40A", callback_data="sel_4Px40A")],
        [InlineKeyboardButton("3Px63A", callback_data="sel_3Px63A"),
         InlineKeyboardButton("4Px63A", callback_data="sel_4Px63A")],
        [InlineKeyboardButton("3Px80A", callback_data="sel_3Px80A"),
         InlineKeyboardButton("4Px80A", callback_data="sel_4Px80A")],
        [InlineKeyboardButton("3Px100A", callback_data="sel_3Px100A"),
         InlineKeyboardButton("4Px100A", callback_data="sel_4Px100A")],
        [InlineKeyboardButton("3Px125A", callback_data="sel_3Px125A"),
         InlineKeyboardButton("4Px125A", callback_data="sel_4Px125A")],
        [InlineKeyboardButton("3Px160A", callback_data="sel_3Px160A"),
         InlineKeyboardButton("4Px160A", callback_data="sel_4Px160A")],
    ]
    
    # Agregar opción para reutilizar última configuración (desde almacenamiento persistente)
    if chat_id_actual in ultima_config_storage and ultima_config_storage[chat_id_actual]:
        keyboard.insert(0, [InlineKeyboardButton("🔄 Usar datos del último tablero", callback_data="reutilizar_ultima")])
    else:
        print("no existe la ultima configuracion")    

    reply_markup = InlineKeyboardMarkup(keyboard)

    if not chat_id_actual:
        logger.error("❌ Error: chat_id_actual es None. No se puede enviar mensaje a Telegram")
        return

    await bot_application.bot.send_message(
        chat_id=chat_id_actual,
        text=(
            "🔧 <b> Dimensionador de Tableros Eléctricos </b>\n\n"
            "Paso 1/5: Selecciona el <b>Seleccionador de Referencia</b>:\n"
            "Voy a recolectar los datos necesarios para el dimensionamiento.\n\n"
        ),
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    
    logger.info(f"✅ Iniciada recolección de datos para chat_id: {chat_id_actual}")

async def reutilizar_ultima(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id_actual = update.effective_chat.id if update else None

    await query.answer()

    # Recuperar desde almacenamiento persistente
    datos_viejos = ultima_config_storage.get(chat_id_actual)
    if not datos_viejos:
        await query.edit_message_text("❌ No hay configuración anterior disponible.")
        return ConversationHandler.END
    
    # Resetear estado global para evitar "proceso en curso"
    from servidor_mcp import resetear_estado_recoleccion
    resetear_estado_recoleccion(chat_id_actual)
    
    # Inicializar si no existen
    if "config" not in context.user_data:
        context.user_data["historial"] = []
    
    context.user_data["config"] = datos_viejos["config"].copy()
    context.user_data["materiales"] = datos_viejos["materiales"].copy()
    
    _registrar_en_historial(context, "Configuración del tablero anterior reutilizada", "user")

    resumen = _generar_resumen_completo(context.user_data)

    keyboard = [
        [InlineKeyboardButton("✅ Dejar como está", callback_data="conf_si")],
        [InlineKeyboardButton("✏️ Modificar algún dato", callback_data="mat_modificar_desde_inicio")],
    ]
    
    await query.edit_message_text(
        f"📋 <b>Datos cargados del tablero anterior:</b>\n\n{resumen}\n\n"
        "¿Quieres confirmarlos o necesitas cambiar algo?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return CONFIRMACION_FINAL

async def seleccionador_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda seleccionador y pregunta tipo de gabinete"""
    query = update.callback_query
    await query.answer()

    # Inicializar datos del usuario si no existen
    if "config" not in context.user_data:
        context.user_data["config"] = {}
        context.user_data["materiales"] = []
        context.user_data["material_temp"] = {}
        context.user_data["historial"] = []

    valor = query.data.replace("sel_", "")
    context.user_data["config"]["seleccionador_ref"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Seleccionador elegido: {valor}", "user")
    
    keyboard = [
        [InlineKeyboardButton("Estanco", callback_data="gab_Estanco")],
        [InlineKeyboardButton("Modular", callback_data="gab_Modular")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ Seleccionador: <b>{valor}</b>\n\n"
        "Paso 2/5: Selecciona el <b>Tipo de Gabinete</b>:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return TIPO_GABINETE


async def tipo_gabinete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda tipo de gabinete y pregunta borneras"""
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("gab_", "")
    context.user_data["config"]["tipo_gabinete"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Tipo de gabinete elegido: {valor}", "user")

    keyboard = [
        [InlineKeyboardButton("✅ SÍ", callback_data="bor_True")],
        [InlineKeyboardButton("❌ NO", callback_data="bor_False")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ Gabinete: <b>{valor}</b>\n\n"
        "Paso 3/5: ¿El tablero <b>tiene borneras</b>?",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return TIENE_BORNERAS


async def tiene_borneras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda borneras y pregunta reserva"""
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("bor_", "") == "True"
    context.user_data["config"]["tiene_borneras"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"¿Tiene borneras?: {'Sí' if valor else 'No'}", "user")

    keyboard = [
        [InlineKeyboardButton("✅ SÍ", callback_data="res_True")],
        [InlineKeyboardButton("❌ NO", callback_data="res_False")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ Borneras: <b>{'SÍ' if valor else 'NO'}</b>\n\n"
        "Paso 4/5: ¿Deseas <b>aplicar reserva</b> de espacio?",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return APLICAR_RESERVA


async def aplicar_reserva(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda reserva y pregunta contrafrente"""
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("res_", "") == "True"
    context.user_data["config"]["aplicar_reserva"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"¿Aplicar reserva?: {'Sí' if valor else 'No'}", "user")

    keyboard = [
        [InlineKeyboardButton("Abisagrado Calado", callback_data="cf_abisagrado-calado")],
        [InlineKeyboardButton("Abisagrado Ciego", callback_data="cf_abisagrado-ciego")],
        [InlineKeyboardButton("Abulonado Ciego", callback_data="cf_abulonado-ciego")],
        [InlineKeyboardButton("Abulonado Calado", callback_data="cf_abulonado-calado")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ Reserva: <b>{'SÍ' if valor else 'NO'}</b>\n\n"
        "Paso 5/5: Selecciona el *Tipo de Contrafrente:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return TIPO_CONTRAFRENTE


async def tipo_contrafrente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Guarda contrafrente y muestra menú de materiales
    SI ES UN GABINETE MODULAR, EL CONTRAFRENTE ES ABISAGRADO-CIEGO O ABULONADO-CIEGO, 
    SI ES UN GABINETE ESTANCO, EL CONTRAFRENTE ES ABISAGRADO-CALADO O ABULONADO-CALADO
    """
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("cf_", "")
    context.user_data["config"]["tipo_contrafrente"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Tipo de contrafrente elegido: {valor}", "user")

    keyboard = [
        [InlineKeyboardButton("➕ Agregar Material", callback_data="mat_agregar")],
        [InlineKeyboardButton("✅ Finalizar y Calcular", callback_data="mat_finalizar")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    materiales_text = _generar_lista_materiales(context.user_data["materiales"])

    await query.edit_message_text(
        f"✅ Contrafrente: <b>{valor}</b>\n\n"
        "📦 <b>MATERIALES AGREGADOS</b>\n"
        f"{materiales_text}\n"
        "¿Qué deseas hacer?",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return MENU_MATERIALES


async def menu_materiales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el menú de materiales"""
    query = update.callback_query
    await query.answer()

    if query.data == "mat_agregar":
        context.user_data["material_temp"] = {}
        
        keyboard = [
            [InlineKeyboardButton("TÉRMICA", callback_data="cat_TERM")],
            [InlineKeyboardButton("DIFERENCIAL", callback_data="cat_DIF")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🔌 <b>Nuevo Material</b>\n\n"
            "Selecciona la <b>Categoría</b>:",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return CATEGORIA

    elif query.data == "mat_finalizar":
        if not context.user_data["materiales"]:
            await query.answer("⚠️ Debes agregar al menos un material", show_alert=True)
            return MENU_MATERIALES

        resumen = _generar_resumen_completo(context.user_data)

        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data="conf_si")],
            [InlineKeyboardButton("✏️ Modificar", callback_data="mat_modificar_desde_inicio")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="conf_no")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"{resumen}\n\n¿Qué deseas hacer?",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return CONFIRMACION_FINAL


async def categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda categoría y solicita cantidad"""
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("cat_", "")
    context.user_data["material_temp"]["categoria"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Nuevo material - Categoría: {valor}", "user")

    await query.edit_message_text(
        f"✅ Categoría: <b>{valor}</b>\n\n"
        "Ingresa la <b>cantidad</b> (número entero):",
        parse_mode="HTML",
    )
    return CANTIDAD


async def cantidad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Valida y guarda cantidad, solicita polos"""
    try:
        valor = int(update.message.text.strip())
        if valor <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Por favor ingresa un número entero positivo:")
        return CANTIDAD

    context.user_data["material_temp"]["cantidad"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Cantidad: {valor}", "user")

    keyboard = [
        [InlineKeyboardButton("1P", callback_data="pol_1P"),
         InlineKeyboardButton("2P", callback_data="pol_2P")],
        [InlineKeyboardButton("3P", callback_data="pol_3P"),
         InlineKeyboardButton("4P", callback_data="pol_4P")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"✅ Cantidad: <b>{valor}</b>\n\n"
        "Selecciona los <b>Polos</b>:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return POLOS


async def polos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda polos y solicita amperaje"""
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("pol_", "")
    context.user_data["material_temp"]["polos"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Polos: {valor}", "user")

    keyboard = [
        [InlineKeyboardButton("10A", callback_data="amp_10A"),
         InlineKeyboardButton("16A", callback_data="amp_16A")],
        [InlineKeyboardButton("20A", callback_data="amp_20A"),
         InlineKeyboardButton("25A", callback_data="amp_25A")],
        [InlineKeyboardButton("32A", callback_data="amp_32A"),
         InlineKeyboardButton("40A", callback_data="amp_40A")],
        [InlineKeyboardButton("50A", callback_data="amp_50A"),
         InlineKeyboardButton("63A", callback_data="amp_63A")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ Polos: <b>{valor}</b>\n\n"
        "Selecciona el <b>Amperaje</b>:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return AMPERAJE


async def amperaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda amperaje y solicita familia"""
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("amp_", "")
    context.user_data["material_temp"]["amperaje"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Amperaje: {valor}", "user")

    keyboard = [
        [InlineKeyboardButton("EZ9", callback_data="fam_EZ9"),
         InlineKeyboardButton("IK60N", callback_data="fam_IK60N")],
        [InlineKeyboardButton("A9R", callback_data="fam_A9R"),
         InlineKeyboardButton("IC60N", callback_data="fam_IC60N")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✅ Amperaje: <b>{valor}</b>\n\n"
        "Selecciona la <b>Familia</b>:",
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
    return FAMILIA


async def familia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda familia y pregunta superinmunizado si es diferencial"""
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("fam_", "")
    context.user_data["material_temp"]["familia"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Familia: {valor}", "user")

    if context.user_data["material_temp"]["categoria"] == "DIF":
        keyboard = [
            [InlineKeyboardButton("✅ SÍ", callback_data="sup_True")],
            [InlineKeyboardButton("❌ NO", callback_data="sup_False")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"✅ Familia: <b>{valor}</b>\n\n"
            "¿El diferencial es <b>superinmunizado</b>?",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return SUPERINMUNIZADO
    else:
        # Si es TÉRMICA, no tiene superinmunizado
        context.user_data["material_temp"]["superinmunizado"] = False
        return await finalizar_material(update, context)


async def superinmunizado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda superinmunizado y finaliza material"""
    query = update.callback_query
    await query.answer()

    valor = query.data.replace("sup_", "") == "True"
    context.user_data["material_temp"]["superinmunizado"] = valor
    
    # Registrar en historial
    _registrar_en_historial(context, f"Superinmunizado: {'Sí' if valor else 'No'}", "user")

    return await finalizar_material(update, context)


async def finalizar_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Agrega el material completo a la lista y vuelve al menú"""
    material = context.user_data["material_temp"].copy()
    context.user_data["materiales"].append(material)

    keyboard = [
        [InlineKeyboardButton("➕ Agregar Otro Material", callback_data="mat_agregar")],
        [InlineKeyboardButton("✅ Continuar", callback_data="mat_finalizar")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    materiales_text = _generar_lista_materiales(context.user_data["materiales"])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            f"✅ Material agregado correctamente\n\n"
            "📦 <b>MATERIALES AGREGADOS</b>\n"
            f"{materiales_text}\n"
            "¿Qué deseas hacer?",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"✅ Material agregado correctamente\n\n"
            "📦 <b>MATERIALES AGREGADOS</b>\n"
            f"{materiales_text}\n"
            "¿Qué deseas hacer?",
            reply_markup=reply_markup,
            parse_mode="HTML",
        )

    return MENU_MATERIALES


async def confirmacion_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja confirmación, cancelación o modificación de datos"""
    query = update.callback_query
    chat_id_actual = query.message.chat_id

    await query.answer()

    if query.data == "conf_no":
        await query.edit_message_text("❌ Dimensionamiento cancelado.")
        _registrar_en_historial(context, "Dimensionamiento cancelado por el usuario.", "model")
        
        # Resetear estado global en servidor_mcp
        from servidor_mcp import resetear_estado_recoleccion
        resetear_estado_recoleccion(chat_id_actual)
        
        context.user_data.clear()
        return ConversationHandler.END
    
    elif query.data == "mat_modificar_desde_inicio":
        from servidor_mcp import resetear_estado_recoleccion, guardar_datos_en_edicion
        
        # Resetear el estado para que el orquestador esté limpio
        resetear_estado_recoleccion(chat_id_actual)
        
        config_actual = context.user_data.get("config", {})
        materiales_actuales = context.user_data.get("materiales", [])
        guardar_datos_en_edicion(config_actual, materiales_actuales) 
        
        context.user_data["historial"] = [] ###

        resumen = _generar_resumen_completo(context.user_data)
        _registrar_en_historial(context, f"Resumen actual para edición: {resumen}", role="model")
        await query.edit_message_text(
            f"📋 <b>Configuración Actual:</b>\n\n{resumen}\n\n"
            "💬 Escribime los cambios que deseas hacer (por ejemplo: 'Cambiar gabinete a Estanco' o 'Agregar 2 térmicas 2P 16A')",
            parse_mode="HTML"
        )
        return CONFIRMACION_FINAL  # Seguir en CONFIRMACION_FINAL para recibir MessageHandler

    await query.edit_message_text("⏳ Procesando dimensionamiento...")

    config = context.user_data["config"]
    materiales = context.user_data["materiales"]

    try:
        # Ejecutar la función de dimensionamiento
        from servidor_mcp import _ejecutar_dimensionamiento_con_datos

        datos_completos = {
            'config_input': config,
            'materiales_input': materiales,
            'chat_id': chat_id_actual,  # Opcional si lo necesitas en el futuro
            'historial': context.user_data.get("historial", [])  # Pasar el historial completo
        }

        logger.info(f"Llamando a dimensionamiento con: {config}")
        resultado = await _ejecutar_dimensionamiento_con_datos(datos_completos)
    
        # Registrar resultado en historial
        resultado_str = resultado if isinstance(resultado, str) else str(resultado)
        _registrar_en_historial(context, resultado_str[:500], "model")  # Registrar primeros 500  caracteres de resultado
        
         # guardo una copia de los parámetros usados para el dimensionamiento para repetir futuras consultas
        ultima_config_guardada = {
            "config": context.user_data["config"].copy(),
            "materiales": context.user_data["materiales"].copy()           
        }

        # borro los temporales
        del context.user_data["config"]
        del context.user_data["materiales"]

        # Enviar resultado
        if isinstance(resultado, str) and os.path.isfile(resultado):
            logger.info(f"Enviando archivo resultado: {resultado}")
            with open(resultado, "rb") as archivo:
                await query.message.reply_document(
                    document=archivo,
                    caption="✅ Dimensionamiento completado"
                )
        else:
            await query.message.reply_text(
                f"✅ <b>Resultado del Dimensionamiento</b>\n\n{resultado}",
                parse_mode="HTML"
            )

    except Exception as e:
        logger.error(f"Error en dimensionamiento: {str(e)}")
        error_msg = f"❌ Error al procesar: {str(e)}"
        _registrar_en_historial(context, error_msg, "model")
        await query.message.reply_text(error_msg)
        
        # Resetear estado global también en caso de error
        from servidor_mcp import resetear_estado_recoleccion
        resetear_estado_recoleccion(chat_id_actual)
        
        ultima_config_guardada = None

    # Guardar en almacenamiento persistente ANTES de limpiar
    if ultima_config_guardada:
        ultima_config_storage[chat_id_actual] = ultima_config_guardada
        logger.info(f"✅ Configuración guardada para reutilización (chat_id: {chat_id_actual})")
    
    # Limpiar datos del usuario después de procesar
    context.user_data.clear()
    
    return ConversationHandler.END


def _generar_lista_materiales(materiales):
    """Genera texto formateado de la lista de materiales"""
    if not materiales:
        return "(ninguno)"

    texto = ""
    for i, mat in enumerate(materiales, 1):
        sup = " - Superinmunizado" if mat.get("superinmunizado") else ""
        texto += (
            f"{i}. {mat['categoria']} | "
            f"{mat['cantidad']}u | {mat['polos']} | "
            f"{mat['amperaje']} | {mat['familia']}{sup}\n"
        )
    return texto


def _registrar_en_historial(context: ContextTypes.DEFAULT_TYPE, texto: str, role: str = "user"):
    """    
    Args:
        context: Contexto del usuario
        texto: Texto a registrar
        role: "user" o "model"
    """
    
    if "historial" not in context.user_data:
        context.user_data["historial"] = []
    
    context.user_data["historial"].append({
        "role": role,
        "parts": [{"text": texto}]
    })

    print(f"Historial actual: {context.user_data['historial']}")  # Depuración
    
    # Mantener solo las últimas 30 interacciones para no exceder límites de tokens
    if len(context.user_data["historial"]) > 30:
        context.user_data["historial"] = context.user_data["historial"][-30:]
    
    logger.debug(f"📝 Historial actualizado ({role}): {texto[:50]}...")


def _generar_resumen_completo(user_data):
    """Genera resumen completo de configuración y materiales"""
    cfg = user_data["config"]
    resumen = (
        "📋 <b>RESUMEN DE CONFIGURACIÓN</b>\n\n"
        f"🔧 Seleccionador: {cfg['seleccionador_ref']}\n"
        f"🗄️ Gabinete: {cfg['tipo_gabinete']}\n"
        f"🔌 Borneras: {'SÍ' if cfg['tiene_borneras'] else 'NO'}\n"
        f"📦 Reserva: {'SÍ' if cfg['aplicar_reserva'] else 'NO'}\n"
        f"🚪 Contrafrente: {cfg['tipo_contrafrente']}\n\n"
        "📦 <strong>MATERIALES</strong>\n"
        f"{_generar_lista_materiales(user_data['materiales'])}"
    )
    return resumen

def crear_bot_application(token: str):
    """
    Crea y configura la aplicación del bot.
    Esta función debe ser llamada al iniciar tu servidor MCP.
    """
    global bot_application
    
    bot_application = Application.builder().token(token).connect_timeout(60).read_timeout(60).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(reutilizar_ultima, pattern="^reutilizar_ultima$"),  # Botón reutilizar config
            CallbackQueryHandler(seleccionador_ref, pattern="^sel_") # entrada al flujo, primer opcion a seleccionar
        ],
        states={
            TIPO_GABINETE: [CallbackQueryHandler(tipo_gabinete, pattern="^gab_")],
            TIENE_BORNERAS: [CallbackQueryHandler(tiene_borneras, pattern="^bor_")],
            APLICAR_RESERVA: [CallbackQueryHandler(aplicar_reserva, pattern="^res_")],
            TIPO_CONTRAFRENTE: [CallbackQueryHandler(tipo_contrafrente, pattern="^cf_")],
            MENU_MATERIALES: [CallbackQueryHandler(menu_materiales, pattern="^mat_")],
            CATEGORIA: [CallbackQueryHandler(categoria, pattern="^cat_")],
            CANTIDAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, cantidad)],
            POLOS: [CallbackQueryHandler(polos, pattern="^pol_")],
            AMPERAJE: [CallbackQueryHandler(amperaje, pattern="^amp_")],
            FAMILIA: [CallbackQueryHandler(familia, pattern="^fam_")],
            SUPERINMUNIZADO: [CallbackQueryHandler(superinmunizado, pattern="^sup_")],
            CONFIRMACION_FINAL: [
                CallbackQueryHandler(confirmacion_final, pattern="^conf_"),
                CallbackQueryHandler(confirmacion_final, pattern="^mat_modificar_desde_inicio$"),  # Manejo de modificación
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edicion_final) # lo modifico para permitir edicion por texto ademas del boton como handlers
            ],
        },
        fallbacks=
        [
            CommandHandler("cancelar", cancelar),
            CallbackQueryHandler(cancelar, pattern = "^cancelar_proceso$")    
        ],
        per_message=False
    )

    bot_application.add_handler(conv_handler)
    
    logger.info("🤖 Bot de Telegram configurado")
    return bot_application

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE): # fallback para salir de la operación de dimensionamiento
    """Cancela y finaliza la conversación actual."""
    # 1. Limpiamos los datos temporales de la recolección
    chat_id_actual = update.effective_chat.id

    
    context.user_data.pop("config", None)
    context.user_data.pop("materiales", None)
    context.user_data.pop("material_temp", None)

    context.user_data.pop("historial", None)

    from servidor_mcp import resetear_estado_recoleccion
    resetear_estado_recoleccion(chat_id_actual)

    # 2. Informamos al usuario
    texto = "🚫 <b>Proceso cancelado.</b>\n\nHe limpiado los datos de este dimensionamiento. ¿En qué más puedo ayudarte?"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(texto, parse_mode="HTML")
    else:
        await update.message.reply_text(texto, parse_mode="HTML")

    # 3. Cerramos el GPS (ConversationHandler)
    return ConversationHandler.END

async def handle_edicion_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    chat_id_actual = update.effective_chat.id

    # Registrar en historial
    _registrar_en_historial(context, user_text, "user")

    # SOLUCIÓN: Guardar snapshot ANTES de procesar
    config_snapshot = context.user_data["config"].copy() if "config" in context.user_data else {}
    materiales_snapshot = [m.copy() for m in context.user_data["materiales"]] if "materiales" in context.user_data else []

    # Guardar datos en edición para que la tool actualizar_datos pueda usarlos
    if "config" in context.user_data and "materiales" in context.user_data:
        from servidor_mcp import guardar_datos_en_edicion
        guardar_datos_en_edicion(
            context.user_data["config"], 
            context.user_data["materiales"]
        )

    # Procesar cambios con IA
    from servidor_mcp import run_orquestador
    
    mensaje_espera = await update.message.reply_text("🔄 Procesando cambios...")
    
    chat_id_actual = update.effective_chat.id

    response = await run_orquestador(context.user_data["historial"], chat_id_original=chat_id_actual)
    _registrar_en_historial(context, response, "model")

    # Si el usuario está en CONFIRMACION_FINAL (modificando configuración)
    if "config" in context.user_data and "materiales" in context.user_data:
        # Resetear estado para evitar bloqueos
        from servidor_mcp import resetear_estado_recoleccion, obtener_datos_en_edicion
        resetear_estado_recoleccion(chat_id_actual)
        
        # SOLUCIÓN: Obtener datos actualizados y compararlos con snapshot
        datos_actualizados = obtener_datos_en_edicion()
        
        # Solo actualizar si realmente hay cambios
        if datos_actualizados:
            nuevos_config = datos_actualizados.get("config", {})
            nuevos_materiales = datos_actualizados.get("materiales", [])
            
            # Verificar si hubo cambios reales comparando con snapshot
            config_cambio = nuevos_config != config_snapshot
            materiales_cambio = nuevos_materiales != materiales_snapshot
            
            if config_cambio or materiales_cambio:
                # Sí hubo cambios, actualizar
                context.user_data["config"] = nuevos_config
                context.user_data["materiales"] = nuevos_materiales
                logger.info(f"✅ Datos actualizados - Config: {config_cambio}, Materiales: {materiales_cambio}")
            else:
                # No hubo cambios, mantener snapshot original
                context.user_data["config"] = config_snapshot
                context.user_data["materiales"] = materiales_snapshot
                logger.info("ℹ️ Sin cambios detectados, manteniendo datos originales")
        else:
            # Si obtener_datos_en_edicion retorna vacío, mantener snapshot
            context.user_data["config"] = config_snapshot
            context.user_data["materiales"] = materiales_snapshot
            logger.warning("⚠️ datos_actualizados está vacío, manteniendo snapshot")
        
        # Generar resumen con datos actuales (ya actualizados o snapshot)
        resumen = _generar_resumen_completo(context.user_data)
        
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data="conf_si")],
            [InlineKeyboardButton("✏️ Modificar de nuevo", callback_data="mat_modificar_desde_inicio")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="conf_no")],
        ]
        
        await mensaje_espera.edit_text(
            f"💡 <b>Respuesta del Asistente:</b>\n\n{response}\n\n"
            f"<b>Configuración Actual:</b>\n\n{resumen}\n\n"
            "¿Qué deseas hacer?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return CONFIRMACION_FINAL
    else:
        # Flujo normal de edición de materiales
        keyboard = [
            [InlineKeyboardButton("✅ Confirmar", callback_data="conf_si")],
            [InlineKeyboardButton("✏️ Modificar", callback_data="mat_modificar_desde_inicio")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="conf_no")],
        ]
        await mensaje_espera.edit_text(
            f"💡 <b>Respuesta:</b>\n\n{response}\n\n¿Qué deseas hacer?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return CONFIRMACION_FINAL


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hola. Soy el asistente de cotizaciones.\n"
        "Podés hacerme consultas sobre cotizaciones y tableros eléctricos, o puedes enviarme un pdf de un unifilar.\n"
        "Para comenzar, probá con el comando /help."
        "Para cancelar una operación en curso, escribí el comando /cancelar."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help - Muestra ayuda"""
    await update.message.reply_text(
        "📚 EJEMPLOS DE USO:\n\n"
        "💬 Consultas simples:\n"
        "• Mostrame todos los gabinetes estanco\n"
        "• ¿Qué gabinetes tenés disponibles de tipo MODULAR?\n"
        "• Busca el seleccionador S750\n\n"
        "🔧 Dimensionamiento:\n"
        "• Quiero dimensionar un tablero eléctrico\n"
    )

async def start_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['historial'] = []
    await update.message.reply_text("🧹 Memoria limpia.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    chat_id_actual = update.effective_chat.id

    logger.info("Mensaje recibido: %s", user_message)

    if 'historial' not in context.user_data:
        context.user_data['historial'] = []

    # Registrar el mensaje del usuario en el historial
    _registrar_en_historial(context, user_message, "user")

    try:
        # Llamada al orquestador MCP con el historial completo
        from servidor_mcp import run_orquestador
        result = await run_orquestador(context.user_data["historial"], chat_id_original=chat_id_actual)

        # Normalizamos salida
        if isinstance(result, dict):
            response_text = result.get("respuesta", str(result))
        else:
            response_text = str(result)

        # Registrar respuesta del modelo en el historial
        _registrar_en_historial(context, response_text, "model")

        if len(response_text) <= 4000:
            await update.message.reply_text(response_text)  
        else:
            for i in range (0, len(response_text), 4000):
                await update.message.reply_text(response_text[i:i+4000])

    except Exception as e:
        logger.exception("Error procesando mensaje")
        response_text = (
            "Ocurrió un error al procesar la consulta.\n"
            "Por favor, revisá el formato o contactá al responsable técnico."
        )
        _registrar_en_historial(context, response_text, "model")
        await update.message.reply_text(response_text)

def callback_desde_mcp(mensaje: str, tipo: str, chat_id:int, **kwargs):
    """Función callback que programa tareas asíncronas"""
    chat_id_actual = chat_id  # Usar el chat_id pasado como parámetro

    try:
        loop = asyncio.get_event_loop()
        
        if tipo == 'iniciar_flujo_recoleccion':
            loop.create_task(iniciar_recoleccion_datos(chat_id=chat_id_actual))
            logger.info(f"✅ Tarea de recolección programada para chat_id={chat_id_actual}")
            
        elif tipo == 'resultado_final':
            # kwargs debería contener 'chat_id' si lo necesitas
            chat_id_param = kwargs.get('chat_id', chat_id_actual)  # Usar global si no viene
            loop.create_task(enviar_mensaje_telegram(chat_id_param, mensaje))
            logger.info("✅ Mensaje programado")
            
        elif tipo == 'enviar_excel':
            archivo_bytes = kwargs.get('archivo_bytes')
            nombre_archivo = kwargs.get('nombre_archivo', 'tablero.xlsx')
            chat_id_param = kwargs.get('chat_id', chat_id_actual)  # Usar global si no viene
            
            if not archivo_bytes:
                logger.error("❌ No se recibió archivo_bytes")
                return
            
            loop.create_task(
                enviar_archivo_telegram(
                    chat_id_param, 
                    archivo_bytes, 
                    nombre_archivo
                )
            )
            logger.info(f"✅ Excel programado: {nombre_archivo}")
            
    except Exception as e:
        logger.error(f"❌ Error en callback_desde_mcp: {e}")
        import traceback
        traceback.print_exc()

async def enviar_mensaje_telegram(chat_id:int, texto:str):
    bot_application.send_message(chat_id=chat_id, text=texto, parse_mode="Markdown")
    return

async def enviar_archivo_telegram(chat_id:int, contenido_bytes:bytes, nombre_archivo: str="dimensionamiento.xlsx"):
    try:
        await bot_application.bot.send_document(
            chat_id=chat_id,
            document=contenido_bytes,
            filename=nombre_archivo,
            caption="✅ Dimensionamiento completado"
        )
        logger.info(f"Archivo enviado a chat_id {chat_id}: {nombre_archivo}")
    except Exception as e:
        logger.error(f"Error enviando archivo a chat_id {chat_id}: {e}")

async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE): # LLAMADA DIRECTA A LA TOOL SIN PASAR POR EL ORQUESTADOR
    
    try:
        # 1. Descargar PDF en un directorio temporal escribible
        import tempfile, time
        documento = update.message.document
        file_name = documento.file_name

        temp_root = Path(tempfile.gettempdir())
        temp_dir = Path(tempfile.gettempdir()) / "cotizabot"


        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(temp_dir, 0o777)  # Asegurar permisos de escritura
        except Exception as e:
            logger.error(f"No se pudo crear temp_dir {temp_dir}: {e}")
            temp_dir = temp_root  # fallback al directorio actual

        file_base = file_name.replace(" ", "_")
        file_clean = "".join(c for c in file_base if c.isalnum() or c in ("_", "-"))

        path_local = temp_dir / f"{int(time.time())}_{file_clean}"
        
        
        if path_local.exists():
            path_local = temp_dir / f"{int(time.time())}_{file_clean}"

        logger.info(f"📥 PDF recibido: {file_name}")
        file = await documento.get_file()
        await update.message.reply_text("📥 Descargando PDF...")
        await file.download_to_drive(str(path_local))

        logger.info(f"✅ PDF guardado temporalmente en: {path_local}")
        
        # 2. Analizar directamente
        mensaje_progreso = await update.message.reply_text(
            "🔍 Analizando esquema unifilar...\n"
            "Esto puede tomar algunos minutos."
        )
        
        # Importar la función de análisis
        from servidor_mcp import analizar_esquema_unifilar
        
        # IMPORTANTE: Pasar la ruta completa como string
        resultado = await analizar_esquema_unifilar(str(path_local.absolute()))
        
        # 3. Formatear y enviar resultado
        if resultado.get("status") == "success":
            materiales = resultado.get("conteo_materiales", {})
            stats = resultado.get("metadatos", {})
            
            respuesta = (
                f"✅ <b>Análisis Completado</b>\n\n"
                f"📄 <b>Proyecto:</b> {resultado.get('proyecto', file_name)}\n\n"
                f"🔌 <b>Materiales Detectados:</b>\n"
            )
            
            if materiales:
                total_items = sum(materiales.values())
                for material, cantidad in sorted(materiales.items()):
                    if cantidad > 0:
                        nombre = material.replace("_", " ").title()
                        respuesta += f"  • {nombre}: {cantidad}\n"
                respuesta += f"\n<b>Total elementos:</b> {total_items}\n"
            else:
                respuesta += "  <i>No se detectaron materiales</i>\n"
            
            respuesta += (
                f"\n📊 <b>Estadísticas:</b>\n"
                f"  • Fragmentos: {stats.get('fragmentos_procesados', 0)}/{stats.get('total_fragmentos', 0)}\n"
                f"  • Tiempo: {stats.get('tiempo_total_segundos', 0)}s\n"
            )
            
            await mensaje_progreso.edit_text(respuesta, parse_mode="HTML")
        else:
            errores = resultado.get("errores", ["Error desconocido"])
            respuesta = (
                f"⚠️ <b>Error en el Análisis</b>\n\n"
                f"No se pudo completar el análisis.\n\n"
                f"<b>Errores:</b>\n"
            )
            for i, error in enumerate(errores[:3], 1):
                respuesta += f"{i}. {error}\n"
            
            if len(errores) > 3:
                respuesta += f"\n<i>...y {len(errores) - 3} errores más</i>"
            
            await mensaje_progreso.edit_text(respuesta, parse_mode="HTML")
            
        if path_local.exists():
            os.remove(path_local)
            logger.info(f"🗑️ Archivo temporal eliminado: {path_local}")
    
    except Exception as e:
        logger.error(f"Error crítico en handle_pdf_directo: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ <b>Error Crítico en Servidor</b>\n\n{str(e)}",
            parse_mode="HTML"
        )

async def main():
    logger.info("Iniciando bot de Telegram...")
    threading.Thread(target = run_health_server, daemon=True).start()
    registrar_callback_recoleccion(callback_desde_mcp)

    app = crear_bot_application(TELEGRAM_TOKEN) # referencia al bot
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("nuevo", start_new)) 
    app.add_handler(CommandHandler("cancelar", cancelar))
    pdf_handler = MessageHandler(filters.Document.PDF & ~filters.COMMAND, handle_pdf) # handler para los pdf de los unifilares
    app.add_handler(pdf_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    await app.initialize()
    await app.start()

    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    logger.info("Bot iniciado. Esperando mensajes...")
    
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
            await app.stop()
            await app.shutdown()
            logger.info("Bot detenido.")
            
if __name__ == "__main__":
    
    asyncio.run(main())