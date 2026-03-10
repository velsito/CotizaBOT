"""
unifilar_handler.py
-------------------
MessageHandler para bot.py (python-telegram-bot v20+ async).

Flujo al recibir un PDF:
  1. Descarga el PDF desde Telegram
  2. Convierte cada página a PNG a 300 DPI con PyMuPDF (fitz)
  3. Ejecuta UnifilarAnalyzer.predict() en cada página (en threadpool,
     para no bloquear el event-loop de PTB)
  4. Acumula conteos de todas las páginas
  5. Envía al chat:
     a. Resumen textual con el conteo total y por página
     b. Cada imagen anotada como foto (o documento si es muy grande)

Integración en main():
    from unifilar_handler import build_unifilar_handler
    ...
    app.add_handler(build_unifilar_handler(analyzer))

Dependencias adicionales (agregar a requirements.txt):
    PyMuPDF==1.24.10
"""

from __future__ import annotations

import asyncio
import gc
import io
import logging
import os
import tempfile
from collections import Counter
from pathlib import Path
import cv2

import fitz  # PyMuPDF
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters

from analyzer import UnifilarAnalyzer, _free_memory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DPI = 300                          # Resolución de conversión PDF → PNG
MAX_PHOTO_BYTES = 9 * 1024 * 1024  # 9 MB: límite de Telegram para sendPhoto
MAX_PHOTO_DIMENSION = 2560 # limite para send_photo
EMOJI = {
    "ok":      "✅",
    "warn":    "⚠️",
    "page":    "📄",
    "chart":   "📊",
    "gear":    "⚙️",
    "img":     "🖼",
    "error":   "❌",
}


# ---------------------------------------------------------------------------
# Lógica de procesamiento (síncrona — se ejecuta en threadpool)
# ---------------------------------------------------------------------------

def _pdf_to_pages_and_analyze(
    pdf_bytes: bytes,
    analyzer: UnifilarAnalyzer,
    tmp_dir: str,
) -> list[dict]:
    """
    Convierte cada página del PDF a PNG y ejecuta la inferencia.

    Retorna una lista de resultados por página:
        [
            {
                "page": 1,
                "counts": {"Disyuntor": 3, "Relé": 1},
                "annotated_path": "/tmp/.../annotated_page_1.png",
            },
            ...
        ]

    Se ejecuta en un threadpool para no bloquear el event-loop.
    """
    results: list[dict] = []

    # Abrir PDF desde bytes (sin escribir a disco)
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(pdf_doc)
    logger.info("PDF recibido: %d página(s).", total_pages)

    for page_num in range(total_pages):
        page_label = page_num + 1
        logger.info("Procesando página %d/%d…", page_label, total_pages)

        # --- Convertir página → PNG en memoria ---
        page = pdf_doc[page_num]
        mat = fitz.Matrix(DPI / 72, DPI / 72)   # 72 DPI es la base de PyMuPDF
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Guardar PNG temporal
        png_path = Path(tmp_dir) / f"page_{page_label}.png"
        pix.save(str(png_path))

        # Liberar pixmap cuanto antes
        pix = None
        gc.collect()

        # --- Inferencia ---
        try:
            result = analyzer.predict(str(png_path))
            results.append(
                {
                    "page":           page_label,
                    "counts":         result["counts"],
                    "annotated_path": result["output_image_path"],
                }
            )
        except Exception as exc:
            logger.exception("Error en página %d: %s", page_label, exc)
            results.append(
                {
                    "page":           page_label,
                    "counts":         {},
                    "annotated_path": None,
                    "error":          str(exc),
                }
            )
        finally:
            # Borrar PNG de entrada para liberar espacio en disco
            png_path.unlink(missing_ok=True)
            _free_memory()

    pdf_doc.close()
    return results


# ---------------------------------------------------------------------------
# Helpers de formateo
# ---------------------------------------------------------------------------

def _format_summary(page_results: list[dict]) -> str:
    """
    Genera el mensaje de texto con el resumen completo.

    Formato Telegram (MarkdownV2).
    """
    total_counter: Counter = Counter()
    lines: list[str] = []

    lines.append(f"{EMOJI['chart']} *Análisis de Plano Unifilar*\n")

    for res in page_results:
        page = res["page"]
        counts = res["counts"]
        error = res.get("error")

        if error:
            lines.append(
                f"{EMOJI['warn']} *Página {page}* — Error: `{_esc(error)}`"
            )
            continue

        total_counter.update(counts)
        page_total = sum(counts.values())
        lines.append(f"{EMOJI['page']} *Página {page}* — {page_total} componentes")

        for label, n in counts.items():
            lines.append(f"    • {_esc(label)}: `{n}`")

    # --- Totales ---
    if total_counter:
        grand_total = sum(total_counter.values())
        lines.append(f"\n{EMOJI['ok']} *Total: {grand_total} componentes*")
        for label, n in total_counter.most_common():
            lines.append(f"    • {_esc(label)}: `{n}`")

    return "\n".join(lines)


def _esc(text: str) -> str:
    """Escapa caracteres especiales para MarkdownV2 de Telegram."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in str(text))


# ---------------------------------------------------------------------------
# Handler asíncrono
# ---------------------------------------------------------------------------

async def handle_unifilar_pdf(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Handler principal. Se registra en main() con build_unifilar_handler().
    """
    analyzer: UnifilarAnalyzer = context.bot_data["analyzer"]
    message = update.effective_message
    chat_id = message.chat_id

    # Telegram envía documentos (no fotos) cuando el archivo supera ~5 MB
    document = message.document
    if document is None:
        await message.reply_text(
            f"{EMOJI['warn']} Por favor, envía el plano unifilar como *archivo PDF*\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    if not document.file_name or not document.file_name.lower().endswith(".pdf"):
        await message.reply_text(
            f"{EMOJI['warn']} Solo se aceptan archivos *PDF*\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # --- Acuse de recibo ---
    status_msg = await message.reply_text(
        f"{EMOJI['gear']} Descargando y preparando el plano\\.\\.\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # 1. Descargar PDF (en memoria)
        tg_file = await context.bot.get_file(document.file_id)
        pdf_buffer = io.BytesIO()
        await tg_file.download_to_memory(pdf_buffer)
        pdf_bytes = pdf_buffer.getvalue()
        del pdf_buffer
        gc.collect()

        logger.info(
            "PDF recibido de chat_id=%s: %.1f MB",
            chat_id,
            len(pdf_bytes) / (1024 * 1024),
        )

        # 2. Procesar en threadpool (no bloquea el event-loop)
        with tempfile.TemporaryDirectory(prefix="unifilar_") as tmp_dir:
            await status_msg.edit_text(
                f"{EMOJI['gear']} Analizando páginas\\.\\.\\. esto puede tardar unos segundos\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )

            loop = asyncio.get_event_loop()
            page_results: list[dict] = await loop.run_in_executor(
                None,                           # usa el ThreadPoolExecutor por defecto
                _pdf_to_pages_and_analyze,
                pdf_bytes,
                analyzer,
                tmp_dir,
            )

            del pdf_bytes
            gc.collect()

            # 3. Enviar resumen textual
            summary_text = _format_summary(page_results)
            await status_msg.edit_text(summary_text, parse_mode=ParseMode.MARKDOWN_V2)

            # 4. Enviar imágenes anotadas
            for res in page_results:
                annotated = res.get("annotated_path")
                if not annotated or not Path(annotated).exists():
                    continue

                await context.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO
                )

                caption = (
                    f" Página {res['page']} — "
                    f"{sum(res['counts'].values())} componentes detectados"
                )
                file_size = Path(annotated).stat().st_size

                with open(annotated, "rb") as img_file:
                    file_size = Path(annotated).stat().st_size
                    
                    # Leer dimensiones sin cargar la imagen completa en RAM
                    img_check = cv2.imread(annotated, cv2.IMREAD_UNCHANGED)
                    h, w = img_check.shape[:2]
                    del img_check
                    gc.collect()
                    
                    too_large_dims = (w > MAX_PHOTO_DIMENSION or h > MAX_PHOTO_DIMENSION)
                    too_large_bytes = (file_size > MAX_PHOTO_BYTES)
                    
                    if too_large_dims or too_large_bytes:
                        # Enviar como documento si se pasa de los límites para telegram 
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=img_file,
                            filename=f"resultados_pagina_{res['page']}.png",
                            caption=caption,
                        )
                    else:
                        await context.bot.send_photo(
                            chat_id=chat_id,
                            photo=img_file,
                            caption=caption,
                        )

                # Borrar imagen anotada una vez enviada
                Path(annotated).unlink(missing_ok=True)
                gc.collect()

    except Exception as exc:
        logger.exception("Error procesando PDF de chat_id=%s", chat_id)
        await status_msg.edit_text(
            f"{EMOJI['error']} Ocurrió un error al procesar el plano:\n`{_esc(str(exc))}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

# ---------------------------------------------------------------------------

def build_unifilar_handler(analyzer: UnifilarAnalyzer) -> MessageHandler:
    """
    Crea y devuelve el MessageHandler listo para registrar en Application.

    Uso en main():
        app.bot_data["analyzer"] = analyzer
        app.add_handler(build_unifilar_handler(analyzer))

    El filtro acepta CUALQUIER documento enviado al bot;
    la validación del tipo PDF se hace dentro del handler.
    """
    return MessageHandler(
        filters.Document.ALL,
        handle_unifilar_pdf,
    )