#!/usr/bin/env python3
"""
Detector de Símbolos Eléctricos con Template Matching usando OpenCV
Utiliza templates de referencia para detectar símbolos sin depender del texto
"""

import cv2
import numpy as np
from pathlib import Path
from pdf2image import convert_from_path
import json
from collections import defaultdict
import tempfile

try:
    from preprocesador_unifilar import PreprocesadorUnifilar # preprocesador para rotar y extraer unifilar
    PREPROCESADOR_DISPONIBLE = True
except ImportError:
    PREPROCESADOR_DISPONIBLE = False
    print("⚠️  preprocesador_unifilar.py no encontrado, preprocesamiento desactivado")


class NumpyEncoder(json.JSONEncoder):
    """JSONEncoder que maneja tipos numpy"""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super(NumpyEncoder, self).default(obj)

class TemplateMatchingDetector:
    """
    Detector robusto usando template matching multi-escala
    """
    
    def __init__(self, templates_dir=None):
        """
        Inicializa el detector
        
        Args:
            templates_dir: Directorio con los templates. Si es None, usa los templates embebidos
        """
        self.templates_dir = Path(templates_dir) if templates_dir else None
        self.templates = {}
        self.resultados = {
            "termicas": 0,
            "luminaria": 0,
            "fusibles": 0,
            "disyuntores": 0,
            "guardamotor": 0,
            "seccionador": 0,
            "contactor": 0,
            "fotocelula": 0
        }
        self.detecciones_detalladas = defaultdict(list)
        
        # Configuración de detección
        self.threshold_base = 0.65  # Umbral base de confianza
        self.scales = np.linspace(0.3, 3.0, 30)  # Escalas para buscar
        self.nms_threshold = 40  # Distancia mínima entre detecciones
        
    def cargar_templates(self):
        """Carga los templates desde archivos PNG"""
        if not self.templates_dir or not self.templates_dir.exists():
            print("⚠️  No se especificó directorio de templates o no existe")
            return False
        
        simbolos = [
            'termica', 'luminaria', 'fusible', 'disyuntor',
            'guardamotor', 'seccionador', 'contactor', 'fotocelula'
        ]
        
        print(f"📁 Cargando templates desde: {self.templates_dir}")
        
        for simbolo in simbolos:
            # Buscar archivos con el nombre del símbolo
            # Soporta variaciones: termica.png, termica_1.png, termica_variante.png
            pattern = f"{simbolo}*.png"
            archivos = list(self.templates_dir.glob(pattern))
            
            if not archivos:
                print(f"   ⚠️  {simbolo}: No encontrado")
                continue
            
            # Cargar todas las variantes del símbolo
            templates_simbolo = []
            for archivo in archivos:
                img = cv2.imread(str(archivo), cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    templates_simbolo.append({
                        'imagen': img,
                        'archivo': archivo.name,
                        'alto': img.shape[0],
                        'ancho': img.shape[1]
                    })
            
            if templates_simbolo:
                self.templates[simbolo] = templates_simbolo
                print(f"   ✅ {simbolo}: {len(templates_simbolo)} variante(s) cargadas")
        
        print(f"\n📊 Total símbolos con templates: {len(self.templates)}\n")
        return len(self.templates) > 0
    
    def crear_templates_desde_imagen_referencia(self, ruta_imagen_ref):
        """
        Crea templates automáticamente desde la imagen de referencia
        cortando cada celda del grid
        """
        print(f"🖼️  Creando templates desde imagen de referencia...")
        
        img = cv2.imread(str(ruta_imagen_ref))
        if img is None:
            print(f"❌ No se pudo cargar: {ruta_imagen_ref}")
            return False
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Detectar bordes del grid
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 100, minLineLength=100, maxLineGap=10)
        
        if lines is None:
            print("❌ No se detectaron líneas del grid")
            return False
        
        # Extraer líneas horizontales y verticales
        h_lines = []
        v_lines = []
        
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
            
            if angle < 10 or angle > 170:  # Horizontal
                h_lines.append((y1 + y2) // 2)
            elif 80 < angle < 100:  # Vertical
                v_lines.append((x1 + x2) // 2)
        
        # Ordenar y eliminar duplicados cercanos
        h_lines = sorted(set([y for y in h_lines]))
        v_lines = sorted(set([x for x in v_lines]))
        
        # Agrupar líneas cercanas
        def agrupar_lineas(lineas, threshold=20):
            if not lineas:
                return []
            grupos = [[lineas[0]]]
            for linea in lineas[1:]:
                if linea - grupos[-1][-1] < threshold:
                    grupos[-1].append(linea)
                else:
                    grupos.append([linea])
            return [int(np.mean(g)) for g in grupos]
        
        h_lines = agrupar_lineas(h_lines)
        v_lines = agrupar_lineas(v_lines)
        
        print(f"   Detectadas {len(h_lines)} filas y {len(v_lines)} columnas")
        
        # Mapeo de posiciones a nombres de símbolos (basado en la imagen de referencia)
        # Fila superior: 7 celdas
        # Fila media: 4 celdas (fila 2)
        simbolos_grid = [
            # Fila superior (índices 0-6)
            ['termica', 'luminaria', 'fusible', 'disyuntor', 'guardamotor', 'seccionador', 'contactor'],
            # Fila inferior (índices 0-3)
            ['fotocelula', 'contactor_2', 'luminaria_2', 'seccionador_2']
        ]
        
        # Crear directorio para templates si no existe
        temp_dir = Path(tempfile.gettempdir()) / "templates_electricos"
        temp_dir.mkdir(exist_ok=True)
        
        templates_creados = 0
        
        # Extraer celdas
        for fila_idx in range(min(len(h_lines) - 1, 2)):  # Solo primeras 2 filas
            y1 = h_lines[fila_idx]
            y2 = h_lines[fila_idx + 1]
            
            num_cols = len(simbolos_grid[fila_idx])
            
            for col_idx in range(min(len(v_lines) - 1, num_cols)):
                x1 = v_lines[col_idx]
                x2 = v_lines[col_idx + 1]
                
                # Extraer celda con margen
                margen = 10
                celda = gray[y1+margen:y2-margen, x1+margen:x2-margen]
                
                if celda.size == 0:
                    continue
                
                # Nombre del símbolo
                nombre = simbolos_grid[fila_idx][col_idx]
                
                # Limpiar la celda (binarizar, eliminar texto)
                _, binary = cv2.threshold(celda, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
                
                # Guardar template
                archivo_template = temp_dir / f"{nombre}.png"
                cv2.imwrite(str(archivo_template), binary)
                templates_creados += 1
                
                print(f"   ✅ Creado: {nombre}.png ({celda.shape[1]}x{celda.shape[0]})")
        
        print(f"\n💾 Templates guardados en: {temp_dir}")
        print(f"📊 Total templates creados: {templates_creados}\n")
        
        # Actualizar directorio de templates
        self.templates_dir = temp_dir
        return True
    
    def non_max_suppression(self, detecciones, threshold=40):
        """
        Elimina detecciones duplicadas cercanas (Non-Maximum Suppression)
        """
        if len(detecciones) == 0:
            return []
        
        # Ordenar por confianza descendente
        detecciones = sorted(detecciones, key=lambda x: x['confianza'], reverse=True)
        
        seleccionadas = []
        
        for det in detecciones:
            # Verificar si está muy cerca de alguna detección ya seleccionada
            muy_cerca = False
            for sel in seleccionadas:
                dist = np.sqrt(
                    (det['centro'][0] - sel['centro'][0])**2 + 
                    (det['centro'][1] - sel['centro'][1])**2
                )
                if dist < threshold:
                    muy_cerca = True
                    break
            
            if not muy_cerca:
                seleccionadas.append(det)
        
        return seleccionadas
    
    def detectar_template_multiescala(self, imagen_gray, template_info, simbolo):
        """
        Detecta un template en múltiples escalas
        """
        template = template_info['imagen']
        detecciones = []
        
        for scale in self.scales:
            # Redimensionar template
            ancho = int(template.shape[1] * scale)
            alto = int(template.shape[0] * scale)
            
            if ancho < 10 or alto < 10 or ancho > imagen_gray.shape[1] or alto > imagen_gray.shape[0]:
                continue
            
            template_scaled = cv2.resize(template, (ancho, alto))
            
            # Template matching
            result = cv2.matchTemplate(imagen_gray, template_scaled, cv2.TM_CCOEFF_NORMED)
            
            # Ajustar threshold según el símbolo (algunos son más difíciles)
            threshold_ajustado = self.threshold_base
            if simbolo in ['guardamotor', 'contactor']:
                threshold_ajustado -= 0.05  # Más permisivo
            elif simbolo in ['termica', 'disyuntor']:
                threshold_ajustado += 0.05  # Más estricto
            
            # Encontrar coincidencias
            locations = np.where(result >= threshold_ajustado)
            
            for pt in zip(*locations[::-1]):
                detecciones.append({
                    'centro': (pt[0] + ancho // 2, pt[1] + alto // 2),
                    'bbox': (pt[0], pt[1], ancho, alto),
                    'confianza': result[pt[1], pt[0]],
                    'escala': scale,
                    'template': template_info['archivo']
                })
        
        return detecciones
    
    def detectar_en_imagen(self, imagen_path, verbose=True):
        """
        Detecta símbolos en una imagen usando template matching
        """
        # Cargar imagen
        img = cv2.imread(str(imagen_path))
        if img is None:
            print(f"❌ No se pudo cargar: {imagen_path}")
            return {}
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        if verbose:
            print(f"🔍 Analizando imagen: {Path(imagen_path).name}")
            print(f"   Tamaño: {gray.shape[1]} x {gray.shape[0]}")
        
        resultados_imagen = {}
        
        # Detectar cada tipo de símbolo
        for simbolo, templates_list in self.templates.items():
            todas_detecciones = []
            
            # Probar con cada variante del template
            for template_info in templates_list:
                detecciones = self.detectar_template_multiescala(
                    gray, template_info, simbolo
                )
                todas_detecciones.extend(detecciones)
            
            # Aplicar NMS para eliminar duplicados
            detecciones_finales = self.non_max_suppression(
                todas_detecciones, 
                self.nms_threshold
            )
            
            if detecciones_finales:
                resultados_imagen[simbolo] = detecciones_finales
                if verbose:
                    print(f"   ✓ {simbolo}: {len(detecciones_finales)} detectado(s)")
        
        return resultados_imagen
    
    def analizar_pdf(self, pdf_path, dpi=200, verbose=True, auto_preprocesar=True):
        """
        Analiza un PDF completo convirtiendo a imágenes
        
        Args:
            pdf_path: Ruta al PDF
            dpi: Resolución para convertir PDF a imagen
            verbose: Mostrar mensajes detallados
            auto_preprocesar: Si True, aplica preprocesamiento (rotación + extracción unifilar)
        """
        # FASE 0: PREPROCESAMIENTO (si está habilitado)
        pdf_a_analizar = pdf_path
        pdf_temporal = None
        
        if auto_preprocesar and PREPROCESADOR_DISPONIBLE:
            print(f"\n{'='*70}")
            print(f"🔧 PREPROCESAMIENTO DEL PDF")
            print(f"{'='*70}\n")
            
            try:
                preprocesador = PreprocesadorUnifilar(pdf_path)
                pdf_temporal = preprocesador.procesar()
                pdf_a_analizar = pdf_temporal
                
                print(f"\n✅ PDF preprocesado listo para template matching\n")
                
            except Exception as e:
                print(f"⚠️  Error en preprocesamiento: {e}")
                print(f"   Continuando con PDF original...\n")
                pdf_a_analizar = pdf_path
        elif auto_preprocesar and not PREPROCESADOR_DISPONIBLE:
            print("⚠️  Preprocesamiento solicitado pero preprocesador_unifilar.py no disponible")
            print("   Continuando con PDF original...\n")
        
        # FASE 1: ANÁLISIS CON TEMPLATE MATCHING
        print(f"\n{'='*70}")
        print(f"📄 Analizando PDF: {Path(pdf_a_analizar).name}")
        print(f"{'='*70}\n")
        
        # Convertir PDF a imágenes
        if verbose:
            print(f"🔄 Convirtiendo PDF a imágenes (DPI: {dpi})...")
        
        try:
            imagenes = convert_from_path(pdf_a_analizar, dpi=dpi)
            if verbose:
                print(f"   ✅ {len(imagenes)} página(s) convertida(s)\n")
        except Exception as e:
            print(f"❌ Error al convertir PDF: {e}")
            
            # Limpiar temporal si existe
            if pdf_temporal and pdf_temporal != pdf_path:
                try:
                    Path(pdf_temporal).unlink()
                except:
                    pass
            
            return None
        
        # Mapeo de nombres de templates a keys de resultados
        # (algunos templates tienen sufijos como _2 que debemos mapear)
        mapeo_nombres = {
            'termica': 'termicas',
            'luminaria': 'luminaria',
            'luminaria_2': 'luminaria',
            'fusible': 'fusibles',
            'disyuntor': 'disyuntores',
            'guardamotor': 'guardamotor',
            'seccionador': 'seccionador',
            'seccionador_2': 'seccionador',
            'contactor': 'contactor',
            'contactor_2': 'contactor',
            'fotocelula': 'fotocelula'
        }
        
        # Analizar cada página
        for num_pagina, imagen in enumerate(imagenes, 1):
            if verbose:
                print(f"📄 Página {num_pagina}:")
            
            # Guardar imagen temporalmente
            temp_img = Path(tempfile.gettempdir()) / f"temp_page_{num_pagina}.png"
            imagen.save(temp_img)
            
            # Detectar símbolos
            detecciones_pagina = self.detectar_en_imagen(temp_img, verbose=verbose)
            
            # Acumular resultados con mapeo correcto
            for simbolo_template, detecciones in detecciones_pagina.items():
                # Mapear nombre del template al key correcto
                simbolo_key = mapeo_nombres.get(simbolo_template, simbolo_template)
                
                self.resultados[simbolo_key] += len(detecciones)
                
                for det in detecciones:
                    self.detecciones_detalladas[simbolo_key].append({
                        'pagina': num_pagina,
                        'posicion': det['centro'],
                        'confianza': float(det['confianza']),
                        'escala': float(det['escala']),
                        'template': det['template']
                    })
            
            # Limpiar archivo temporal de página
            temp_img.unlink()
            
            if verbose:
                print()
        
        # Limpiar PDF temporal si se creó
        if pdf_temporal and pdf_temporal != pdf_path:
            try:
                Path(pdf_temporal).unlink()
                if verbose:
                    print(f"🗑️  PDF temporal eliminado: {Path(pdf_temporal).name}\n")
            except:
                pass
        
        return self.resultados
    
    def mostrar_resultados(self):
        """Muestra resumen de resultados"""
        print("="*70)
        print("📊 RESULTADOS - TEMPLATE MATCHING")
        print("="*70)
        
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
        
        total = sum(self.resultados.values())
        
        for material, cantidad in self.resultados.items():
            icono = iconos.get(material, "•")
            nombre = material.upper().replace("_", " ")
            
            # Mostrar confianza promedio si hay detecciones
            if cantidad > 0 and material in self.detecciones_detalladas:
                confianzas = [d['confianza'] for d in self.detecciones_detalladas[material]]
                conf_promedio = np.mean(confianzas)
                print(f"{icono} {nombre:.<45} {cantidad:>3}  (conf: {conf_promedio:.2f})")
            else:
                print(f"{icono} {nombre:.<45} {cantidad:>3}")
        
        print("="*70)
        print(f"{'TOTAL':.<49} {total:>3}")
        print("="*70)
    
    def exportar_json(self, archivo="resultados_template_matching.json"):
        """Exporta resultados a JSON"""
        datos = {
            "resumen": self.resultados,
            "total_elementos": sum(self.resultados.values()),
            "detalle": dict(self.detecciones_detalladas),
            "configuracion": {
                "threshold": self.threshold_base,
                "escalas": f"{self.scales[0]:.2f} - {self.scales[-1]:.2f}",
                "num_escalas": len(self.scales)
            }
        }
        
        with open(archivo, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        
        print(f"\n💾 Resultados: {archivo}\n")
        return datos
    
    def visualizar_detecciones(self, imagen_path, output_path=None):
        """
        Crea una imagen con las detecciones marcadas
        """
        img = cv2.imread(str(imagen_path))
        if img is None:
            return None
        
        # Colores por tipo de símbolo
        colores = {
            'termicas': (0, 255, 0),      # Verde
            'luminaria': (255, 255, 0),    # Amarillo
            'fusibles': (255, 0, 0),       # Rojo
            'disyuntores': (255, 165, 0),  # Naranja
            'guardamotor': (128, 0, 128),  # Púrpura
            'seccionador': (0, 255, 255),  # Cyan
            'contactor': (255, 0, 255),    # Magenta
            'fotocelula': (0, 128, 255)    # Azul claro
        }
        
        # Dibujar detecciones
        for simbolo, detecciones in self.detecciones_detalladas.items():
            color = colores.get(simbolo, (255, 255, 255))
            
            for det in detecciones:
                x, y = det['posicion']
                cv2.circle(img, (int(x), int(y)), 10, color, 2)
                cv2.putText(
                    img, 
                    simbolo[:3].upper(), 
                    (int(x) + 15, int(y)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 
                    0.5, 
                    color, 
                    1
                )
        
        if output_path:
            cv2.imwrite(str(output_path), img)
            print(f"🖼️  Visualización guardada: {output_path}")
        
        return img


def main():
    import sys
    
    print("="*70)
    print("🔍 DETECTOR CON TEMPLATE MATCHING + PREPROCESAMIENTO")
    print("="*70 + "\n")
    
    if len(sys.argv) < 2:
        print("""
Uso: python detector_template_matching.py <pdf> [opciones]

Opciones:
  --templates <dir>          Directorio con templates PNG
  --crear-templates <img>    Crear templates desde imagen de referencia
  --dpi <numero>            DPI para conversión (default: 200)
  --threshold <numero>       Umbral de confianza (default: 0.65)
  --visualizar              Guardar imagen con detecciones marcadas
  --sin-preprocesar         Desactivar preprocesamiento automático

Ejemplos:
  # Con preprocesamiento automático (recomendado)
  python detector_template_matching.py plano.pdf --crear-templates REFERENCIAS.png
  
  # Sin preprocesamiento (PDF ya es unifilar puro)
  python detector_template_matching.py unifilar.pdf --crear-templates REFERENCIAS.png --sin-preprocesar
  
  # Usar templates existentes
  python detector_template_matching.py plano.pdf --templates ./templates
  
  # Con visualización
  python detector_template_matching.py plano.pdf --crear-templates REFERENCIAS.png --visualizar
        """)
        return
    
    pdf_path = sys.argv[1]
    
    if not Path(pdf_path).exists():
        print(f"❌ No existe: {pdf_path}")
        return
    
    # Parsear argumentos
    templates_dir = None
    imagen_ref = None
    dpi = 200
    threshold = 0.65
    visualizar = "--visualizar" in sys.argv
    auto_preprocesar = "--sin-preprocesar" not in sys.argv
    
    if "--templates" in sys.argv:
        idx = sys.argv.index("--templates")
        templates_dir = sys.argv[idx + 1]
    
    if "--crear-templates" in sys.argv:
        idx = sys.argv.index("--crear-templates")
        imagen_ref = sys.argv[idx + 1]
    
    if "--dpi" in sys.argv:
        idx = sys.argv.index("--dpi")
        dpi = int(sys.argv[idx + 1])
    
    if "--threshold" in sys.argv:
        idx = sys.argv.index("--threshold")
        threshold = float(sys.argv[idx + 1])
    
    # Mostrar configuración
    print(f"📋 Configuración:")
    print(f"   PDF: {Path(pdf_path).name}")
    print(f"   DPI: {dpi}")
    print(f"   Threshold: {threshold}")
    print(f"   Preprocesamiento: {'✅ Habilitado' if auto_preprocesar else '❌ Desactivado'}")
    if not PREPROCESADOR_DISPONIBLE and auto_preprocesar:
        print(f"   ⚠️  preprocesador_unifilar.py no encontrado")
    print()
    
    # Crear detector
    detector = TemplateMatchingDetector(templates_dir)
    detector.threshold_base = threshold
    
    # Crear templates si se especificó
    if imagen_ref:
        if not Path(imagen_ref).exists():
            print(f"❌ Imagen de referencia no existe: {imagen_ref}")
            return
        
        if not detector.crear_templates_desde_imagen_referencia(imagen_ref):
            print("❌ No se pudieron crear los templates")
            return
    
    # Cargar templates
    if not detector.cargar_templates():
        print("❌ No se cargaron templates")
        return
    
    # Analizar PDF (con o sin preprocesamiento)
    resultados = detector.analizar_pdf(
        pdf_path, 
        dpi=dpi, 
        auto_preprocesar=auto_preprocesar
    )
    
    if resultados:
        detector.mostrar_resultados()
        detector.exportar_json()
        
        # Visualizar si se solicitó
        if visualizar:
            # Para visualización, usar el PDF original convertido
            # (la visualización no necesita preprocesamiento)
            print("\n🎨 Generando visualización...")
            imagenes = convert_from_path(pdf_path, dpi=dpi)
            if imagenes:
                temp_img = Path(tempfile.gettempdir()) / "temp_visual.png"
                imagenes[0].save(temp_img)
                
                output_visual = Path(pdf_path).stem + "_detecciones.png"
                detector.visualizar_detecciones(temp_img, output_visual)
                
                temp_img.unlink()
        
        print("✅ Análisis completado")


if __name__ == "__main__":
    main()