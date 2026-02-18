#!/usr/bin/env python3
"""
Preprocesador de PDFs Unifilares - VERSIÓN CORREGIDA
Extrae solo la sección unifilar (mitad inferior) de PDFs que combinan topográfico + unifilar
"""

import pdfplumber
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
import tempfile

class PreprocesadorUnifilar:
    """Preprocesa PDFs para extraer solo la sección unifilar"""
    
    def __init__(self, ruta_pdf):
        self.ruta_pdf = ruta_pdf
        self.pdf_procesado = None
    
    def detectar_orientacion(self):
        """Detecta si el PDF está en vertical u horizontal"""
        with pdfplumber.open(self.ruta_pdf) as pdf:
            pagina = pdf.pages[0]
            ancho = pagina.width
            alto = pagina.height
            
            # Si altura > ancho, está en vertical
            es_vertical = alto > ancho
            
            print(f"📏 Dimensiones originales: {ancho:.1f} x {alto:.1f}")
            print(f"   Orientación: {'VERTICAL ↕' if es_vertical else 'HORIZONTAL ↔'}")
            
            return {
                'es_vertical': es_vertical,
                'ancho': ancho,
                'alto': alto,
                'ratio': alto / ancho if ancho > 0 else 1
            }
    
    def rotar_y_extraer_unifilar(self, archivo_salida=None):
        """
        Rota el PDF si es necesario Y extrae el unifilar en un solo paso.
        Esto evita problemas con las dimensiones cambiadas.
        """
        orientacion = self.detectar_orientacion()
        
        if archivo_salida is None:
            temp_dir = tempfile.gettempdir()
            archivo_salida = Path(temp_dir) / f"unifilar_{Path(self.ruta_pdf).name}"
        
        reader = PdfReader(self.ruta_pdf)
        writer = PdfWriter()
        
        for page_num, page in enumerate(reader.pages):
            print(f"\n   📄 Procesando página {page_num + 1}...")
            
            # Obtener dimensiones originales
            media_box = page.mediabox
            ancho_orig = float(media_box.width)
            alto_orig = float(media_box.height)

            # Detectar orientación por página (más robusto que usar solo la primera página)
            es_vertical_pagina = alto_orig > ancho_orig

            if es_vertical_pagina:
                # PDF VERTICAL: TOPOGRÁFICO arriba, UNIFILAR abajo
                print(f"      ℹ️  PDF en VERTICAL")
                print(f"      🔄 Rotando a horizontal y extrayendo unifilar (mitad inferior)...")

                # Recortar la mitad inferior en coordenadas originales (altura)
                mitad_alto = alto_orig / 2
                box = RectangleObject([0, 0, float(ancho_orig), float(mitad_alto)])
                try:
                    page.cropbox = box
                except Exception:
                    try:
                        page.mediabox = box
                    except Exception:
                        pass

                # Ahora rotar 270° para ponerlo en horizontal (mantener lectura)
                try:
                    page.rotate_clockwise(270)
                except Exception:
                    try:
                        page.rotate(270)
                    except Exception:
                        pass

                print(f"      ✅ Extraída mitad inferior y rotado 270°")
                print(f"      📐 Resultado aproximado: {ancho_orig:.1f} x {mitad_alto:.1f} (antes de rotación)")
                
            else:
                # PDF HORIZONTAL: TOPOGRÁFICO izquierda, UNIFILAR derecha
                # O puede ser que esté dividido arriba/abajo
                print(f"      ℹ️  PDF en HORIZONTAL")
                print(f"      ✂️  Extrayendo mitad inferior (unifilar)...")
                
                # Para PDF horizontal, asumimos división arriba/abajo: recortar por altura
                mitad_alto = alto_orig / 2
                box = RectangleObject([0, 0, float(ancho_orig), float(mitad_alto)])
                try:
                    page.cropbox = box
                except Exception:
                    try:
                        page.mediabox = box
                    except Exception:
                        pass
                
                print(f"      ✅ Extraído mitad inferior")
                print(f"      📐 Resultado: {ancho_orig:.1f} x {mitad_alto:.1f}")
            
            writer.add_page(page)
        
        # Guardar resultado
        with open(archivo_salida, 'wb') as f:
            writer.write(f)
        
        # Verificar resultado final
        print(f"\n   🔍 Verificando resultado...")
        with pdfplumber.open(archivo_salida) as pdf:
            pagina = pdf.pages[0]
            print(f"   📏 Dimensiones finales: {pagina.width:.1f} x {pagina.height:.1f}")
            
            # Verificar que quedó horizontal
            if pagina.height > pagina.width:
                print(f"   ⚠️  ADVERTENCIA: El resultado está en VERTICAL")
                print(f"      Puede haber un problema con el procesamiento")
            else:
                print(f"   ✅ Resultado correcto: PDF horizontal con unifilar")
        
        print(f"\n   💾 Unifilar extraído: {archivo_salida}")
        return str(archivo_salida)
    
    def procesar(self, mantener_archivos_temp=False):
        """
        Proceso completo: detectar orientación, rotar si es necesario y extraer unifilar
        """
        print("="*70)
        print("🔧 PREPROCESANDO PDF PARA EXTRAER UNIFILAR")
        print("="*70)
        print(f"📄 Archivo: {Path(self.ruta_pdf).name}\n")
        
        # Rotar y extraer en un solo paso
        temp_dir = tempfile.gettempdir()
        nombre_final = f"unifilar_procesado_{Path(self.ruta_pdf).name}"
        archivo_final = Path(temp_dir) / nombre_final
        
        pdf_unifilar = self.rotar_y_extraer_unifilar(archivo_final)
        
        self.pdf_procesado = pdf_unifilar
        
        print("\n" + "="*70)
        print("✅ PREPROCESAMIENTO COMPLETADO")
        print("="*70)
        print(f"📄 Unifilar listo: {pdf_unifilar}\n")
        
        return pdf_unifilar
    
    def obtener_pdf_procesado(self):
        """Retorna la ruta del PDF procesado"""
        return self.pdf_procesado


class DetectorConPreprocesamiento:
    """
    Wrapper que integra preprocesamiento + detección
    """
    
    def __init__(self, DetectorClass):
        self.DetectorClass = DetectorClass
    
    def analizar_con_preprocesamiento(self, ruta_pdf_original):
        """
        Analiza un PDF con preprocesamiento automático
        """
        # Paso 1: Preprocesar
        print("\n" + "🎯 FASE 1: PREPROCESAMIENTO\n")
        preprocesador = PreprocesadorUnifilar(ruta_pdf_original)
        pdf_unifilar = preprocesador.procesar()
        
        # Paso 2: Detectar
        print("\n" + "🎯 FASE 2: DETECCIÓN DE SÍMBOLOS\n")
        detector = self.DetectorClass(pdf_unifilar)
        resultados = detector.analizar()
        
        if resultados:
            detector.mostrar_resultados()
            detector.exportar_json()
        
        return resultados, pdf_unifilar


def main():
    """Función de prueba"""
    import sys
    
    if len(sys.argv) < 2:
        print("Uso: python preprocesador_unifilar.py <pdf>")
        print("\nOpciones:")
        print("  --solo-preprocesar: Solo preprocesa sin analizar")
        return
    
    ruta_pdf = sys.argv[1]
    
    if not Path(ruta_pdf).exists():
        print(f"❌ No existe: {ruta_pdf}")
        return
    
    # Modo 1: Solo preprocesar
    if "--solo-preprocesar" in sys.argv:
        preprocesador = PreprocesadorUnifilar(ruta_pdf)
        pdf_procesado = preprocesador.procesar(mantener_archivos_temp=True)
        print(f"\n📄 PDF unifilar guardado en: {pdf_procesado}")
    
    # Modo 2: Preprocesar + Analizar
    else:
        try:
            # Importar el detector (ajustar según el detector que uses)
            from detector_simbolos_electricos import DetectorSimbolosElectricos
            
            wrapper = DetectorConPreprocesamiento(DetectorSimbolosElectricos)
            resultados, pdf_unifilar = wrapper.analizar_con_preprocesamiento(ruta_pdf)
            
            print(f"\n📊 Análisis completo")
            print(f"   PDF unifilar temporal: {pdf_unifilar}")
            
        except ImportError:
            print("⚠️  No se encontró el detector. Ejecutando solo preprocesamiento.")
            preprocesador = PreprocesadorUnifilar(ruta_pdf)
            pdf_procesado = preprocesador.procesar(mantener_archivos_temp=True)
            print(f"\n📄 PDF unifilar guardado en: {pdf_procesado}")


if __name__ == "__main__":
    main()