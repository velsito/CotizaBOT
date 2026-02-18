#!/usr/bin/env python3
"""
Detector Híbrido Completo:
Template Matching (OpenCV) + Análisis de Texto (pdfplumber) + Preprocesamiento
"""

import sys
from pathlib import Path
import json
import tempfile
import numpy as np

from preprocesador_unifilar import PreprocesadorUnifilar
from detector_simbolos_electricos import DetectorSimbolosElectricos
from detector_template_matching import TemplateMatchingDetector, NumpyEncoder

class DetectorHibridoCompleto:
    """
    Detector que combina 3 métodos:
    1. Preprocesamiento (orientación + extracción)
    2. Template Matching (OpenCV - robusto, no depende de texto)
    3. Análisis de Texto (pdfplumber - rápido, preciso para IDs)
    
    Fusiona resultados con votación ponderada
    """
    
    def __init__(self, ruta_pdf, templates_dir=None, auto_preprocesar=True):
        self.ruta_pdf_original = ruta_pdf
        self.templates_dir = templates_dir
        self.auto_preprocesar = auto_preprocesar
        
        self.pdf_procesado = None
        self.resultados_template = None
        self.resultados_texto = None
        self.resultados_fusionados = {
            "termicas": 0,
            "luminaria": 0,
            "fusibles": 0,
            "disyuntores": 0,
            "guardamotor": 0,
            "seccionador": 0,
            "contactor": 0,
            "fotocelula": 0
        }
        self.metadatos_fusion = {}
    
    def preprocesar(self):
        """Fase 1: Preprocesamiento del PDF"""
        if not self.auto_preprocesar:
            print("⏭️  Preprocesamiento desactivado")
            self.pdf_procesado = self.ruta_pdf_original
            return self.pdf_procesado
        
        print("\n" + "="*80)
        print("🎯 FASE 1: PREPROCESAMIENTO")
        print("="*80 + "\n")
        
        preprocesador = PreprocesadorUnifilar(self.ruta_pdf_original)
        self.pdf_procesado = preprocesador.procesar()
        
        return self.pdf_procesado
    
    def analizar_con_template_matching(self, dpi=300):
        """Fase 2: Análisis con Template Matching"""
        print("\n" + "="*80)
        print("🎯 FASE 2: DETECCIÓN CON TEMPLATE MATCHING (OpenCV)")
        print("="*80 + "\n")
        
        detector_tm = TemplateMatchingDetector(self.templates_dir)
        
        # Cargar templates
        if not detector_tm.cargar_templates():
            print("⚠️  No se cargaron templates, saltando template matching")
            return None
        
        # Analizar
        self.resultados_template = detector_tm.analizar_pdf(
            self.pdf_procesado, 
            dpi=dpi, 
            verbose=True
        )
        
        return self.resultados_template
    
    def analizar_con_texto(self):
        """Fase 3: Análisis de Texto"""
        print("\n" + "="*80)
        print("🎯 FASE 3: DETECCIÓN CON ANÁLISIS DE TEXTO")
        print("="*80 + "\n")
        
        detector_texto = DetectorSimbolosElectricos(self.pdf_procesado)
        self.resultados_texto = detector_texto.analizar()
        
        return self.resultados_texto
    
    def fusionar_resultados(self):
        """
        Fase 4: Fusión Inteligente de Resultados
        
        Estrategia de fusión por elemento:
        
        - TÉRMICAS, DISYUNTORES, SECCIONADORES: 
          Priorizar texto (tienen IDs únicos como TM1, INS, etc.)
        
        - FUSIBLES, LUMINARIAS:
          Promedio ponderado (texto 60%, template 40%)
          El texto captura multiplicadores, template es más visual
        
        - GUARDAMOTOR, CONTACTOR, FOTOCÉLULA:
          Priorizar template matching (geometría compleja)
        """
        print("\n" + "="*80)
        print("🎯 FASE 4: FUSIÓN INTELIGENTE DE RESULTADOS")
        print("="*80 + "\n")
        
        if not self.resultados_texto:
            print("⚠️  No hay resultados de texto")
            if self.resultados_template:
                self.resultados_fusionados = self.resultados_template.copy()
            return
        
        # Elementos que priorizan TEXTO (tienen IDs únicos)
        elementos_texto = ['termicas', 'disyuntores', 'seccionador']
        
        # Elementos que usan PROMEDIO PONDERADO
        elementos_promedio = ['fusibles', 'luminaria']
        
        # Elementos que priorizan TEMPLATE (geometría compleja)
        elementos_template = ['guardamotor', 'contactor', 'fotocelula']
        
        for elemento in self.resultados_fusionados.keys():
            texto_val = self.resultados_texto.get(elemento, 0)
            template_val = self.resultados_template.get(elemento, 0) if self.resultados_template else 0
            
            if elemento in elementos_texto:
                # Priorizar texto
                self.resultados_fusionados[elemento] = texto_val
                self.metadatos_fusion[elemento] = {
                    'metodo': 'texto_prioritario',
                    'texto': texto_val,
                    'template': template_val,
                    'confianza': 0.95 if texto_val > 0 else 0.0
                }
                print(f"   {elemento}: TEXTO prioritario → {texto_val}")
            
            elif elemento in elementos_promedio:
                # Promedio ponderado: 60% texto, 40% template
                if texto_val > 0 and template_val > 0:
                    fusionado = int(round(texto_val * 0.6 + template_val * 0.4))
                    self.resultados_fusionados[elemento] = fusionado
                    self.metadatos_fusion[elemento] = {
                        'metodo': 'promedio_ponderado',
                        'texto': texto_val,
                        'template': template_val,
                        'fusionado': fusionado,
                        'confianza': 0.85
                    }
                    print(f"   {elemento}: PROMEDIO → {fusionado} (texto:{texto_val}, template:{template_val})")
                elif texto_val > 0:
                    self.resultados_fusionados[elemento] = texto_val
                    self.metadatos_fusion[elemento] = {
                        'metodo': 'solo_texto',
                        'texto': texto_val,
                        'confianza': 0.80
                    }
                    print(f"   {elemento}: Solo TEXTO → {texto_val}")
                elif template_val > 0:
                    self.resultados_fusionados[elemento] = template_val
                    self.metadatos_fusion[elemento] = {
                        'metodo': 'solo_template',
                        'template': template_val,
                        'confianza': 0.75
                    }
                    print(f"   {elemento}: Solo TEMPLATE → {template_val}")
            
            elif elemento in elementos_template:
                # Priorizar template matching
                if template_val > 0:
                    self.resultados_fusionados[elemento] = template_val
                    self.metadatos_fusion[elemento] = {
                        'metodo': 'template_prioritario',
                        'texto': texto_val,
                        'template': template_val,
                        'confianza': 0.80
                    }
                    print(f"   {elemento}: TEMPLATE prioritario → {template_val}")
                elif texto_val > 0:
                    # Fallback a texto si template no detectó
                    self.resultados_fusionados[elemento] = texto_val
                    self.metadatos_fusion[elemento] = {
                        'metodo': 'texto_fallback',
                        'texto': texto_val,
                        'confianza': 0.70
                    }
                    print(f"   {elemento}: Fallback TEXTO → {texto_val}")
        
        print()
        return self.resultados_fusionados
    
    def analizar_completo(self, dpi_template=150, crear_templates_auto=False, imagen_referencia=None):
        """
        Análisis completo con todos los métodos
        """
        print("\n" + "="*80)
        print("🔍 DETECTOR HÍBRIDO COMPLETO")
        print("   Template Matching + Análisis de Texto + Preprocesamiento")
        print("="*80)
        print(f"📄 Archivo: {Path(self.ruta_pdf_original).name}")
        print("="*80 + "\n")
        
        # Crear templates automáticamente si se especificó
        if crear_templates_auto and imagen_referencia:
            print("\n🖼️  CREACIÓN AUTOMÁTICA DE TEMPLATES\n")
            detector_temp = TemplateMatchingDetector()
            if detector_temp.crear_templates_desde_imagen_referencia(imagen_referencia):
                self.templates_dir = detector_temp.templates_dir
                print(f"✅ Templates creados en: {self.templates_dir}\n")
        
        # Fase 1: Preprocesar
        self.preprocesar()
        
        # Fase 2: Template Matching
        self.analizar_con_template_matching(dpi=dpi_template)
        
        # Fase 3: Texto
        self.analizar_con_texto()
        
        # Fase 4: Fusionar
        self.fusionar_resultados()
        
        return self.resultados_fusionados
    
    def mostrar_resultados(self):
        """Muestra resultados fusionados"""
        print("\n" + "="*80)
        print("📊 RESULTADOS FINALES - DETECTOR HÍBRIDO")
        print("="*80)
        
        iconos = {
            "termicas": "🔌",
            "luminaria": "💡",
            "fusibles": "🔒",
            "disyuntores": "⚡",
            "guardamotor": "⚙️",
            "seccionador": "🔧",
            "contactor": "🔄",
            "fotocelula": "📷"
        }
        
        total = sum(self.resultados_fusionados.values())
        
        for material, cantidad in self.resultados_fusionados.items():
            icono = iconos.get(material, "•")
            nombre = material.upper().replace("_", " ")
            
            # Mostrar método y confianza
            if material in self.metadatos_fusion:
                meta = self.metadatos_fusion[material]
                metodo = meta.get('metodo', 'N/A')
                confianza = meta.get('confianza', 0.0)
                print(f"{icono} {nombre:.<35} {cantidad:>3}  [{metodo[:12]:12s} {confianza:.2f}]")
            else:
                print(f"{icono} {nombre:.<35} {cantidad:>3}")
        
        print("="*80)
        print(f"{'TOTAL':.<39} {total:>3}")
        print("="*80)
    
    def exportar_json(self, archivo="resultados_hibrido_completo.json"):
        """Exporta resultados completos"""
        datos = {
            "pdf_original": self.ruta_pdf_original,
            "pdf_procesado": self.pdf_procesado,
            "metodos_usados": {
                "preprocesamiento": self.auto_preprocesar,
                "template_matching": self.resultados_template is not None,
                "analisis_texto": self.resultados_texto is not None
            },
            "resultados_individuales": {
                "template_matching": self.resultados_template,
                "analisis_texto": self.resultados_texto
            },
            "resultados_fusionados": self.resultados_fusionados,
            "metadatos_fusion": self.metadatos_fusion,
            "total_elementos": sum(self.resultados_fusionados.values())
        }
        
        with open(archivo, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        
        print(f"\n💾 Resultados: {archivo}\n")
        return datos
    
    def limpiar_temporales(self):
        """Limpia archivos temporales"""
        if self.pdf_procesado and self.pdf_procesado != self.ruta_pdf_original:
            try:
                Path(self.pdf_procesado).unlink()
                print(f"🗑️  Temporal eliminado: {Path(self.pdf_procesado).name}")
            except:
                pass


def main():
    if len(sys.argv) < 2:
        print("""
Uso: python detector_hibrido_completo.py <pdf> [opciones]

Opciones:
  --templates <dir>               Directorio con templates PNG
  --crear-templates <referencia>  Crear templates desde imagen de referencia
  --sin-preprocesar               Desactivar preprocesamiento
  --dpi <numero>                  DPI para template matching (default: 150)

Ejemplos:
  # Con creación automática de templates
  python detector_hibrido_completo.py plano.pdf --crear-templates REFERENCIAS.png
  
  # Usando templates existentes
  python detector_hibrido_completo.py plano.pdf --templates ./templates
  
  # Sin preprocesamiento (PDF ya es unifilar puro)
  python detector_hibrido_completo.py unifilar.pdf --crear-templates REFERENCIAS.png --sin-preprocesar
        """)
        return
    
    pdf_path = sys.argv[1]
    
    if not Path(pdf_path).exists():
        print(f"❌ No existe: {pdf_path}")
        return
    
    # Parsear argumentos
    templates_dir = None
    imagen_ref = None
    auto_preprocesar = "--sin-preprocesar" not in sys.argv
    dpi = 300
    
    if "--templates" in sys.argv:
        idx = sys.argv.index("--templates")
        templates_dir = sys.argv[idx + 1]
    
    if "--crear-templates" in sys.argv:
        idx = sys.argv.index("--crear-templates")
        imagen_ref = sys.argv[idx + 1]
        if not Path(imagen_ref).exists():
            print(f"❌ Imagen de referencia no existe: {imagen_ref}")
            return
    
    if "--dpi" in sys.argv:
        idx = sys.argv.index("--dpi")
        dpi = int(sys.argv[idx + 1])
    
    # Crear detector híbrido
    detector = DetectorHibridoCompleto(
        pdf_path, 
        templates_dir=templates_dir,
        auto_preprocesar=auto_preprocesar
    )
    
    # Analizar
    resultados = detector.analizar_completo(
        dpi_template=dpi,
        crear_templates_auto=(imagen_ref is not None),
        imagen_referencia=imagen_ref
    )
    
    if resultados:
        detector.mostrar_resultados()
        detector.exportar_json()
        
        print("\n✅ Análisis completado")
        
        # Limpiar temporales
        if input("\n¿Eliminar archivos temporales? (s/n): ").lower() == 's':
            detector.limpiar_temporales()


if __name__ == "__main__":
    main()