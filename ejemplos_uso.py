"""
Ejemplos de Uso - CotizaBOT Template Matching
Casos de uso comunes y patrones de integración
"""

from template_matcher import TemplateMatcher
from mcp_integration import MaterialDetectionTool
import json


def ejemplo_1_uso_basico():
    """
    Ejemplo 1: Detección básica en un plano
    """
    print("=" * 70)
    print("EJEMPLO 1: Detección Básica")
    print("=" * 70)
    
    # Crear detector
    matcher = TemplateMatcher(
        templates_dir='./templates',
        threshold=0.7
    )
    
    # Procesar plano
    results, image, detections = matcher.detect('topo.pdf', page_num=0)
    
    # Mostrar conteos
    print(f"\n📊 Resultados:")
    print(f"Total de componentes detectados: {results['total_detections']}")
    
    for material, count in results['counts'].items():
        print(f"  • {material}: {count}")
    
    # Guardar visualización
    matcher.visualize_detections(image, detections, 'output_ejemplo1.png')
    
    # Guardar JSON
    with open('output_ejemplo1.json', 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print("\n✅ Archivos generados:")
    print("  - output_ejemplo1.json")
    print("  - output_ejemplo1.png")


def ejemplo_2_multiples_formatos():
    """
    Ejemplo 2: Procesar dos formatos de plano diferentes
    """
    print("\n" + "=" * 70)
    print("EJEMPLO 2: Múltiples Formatos de Plano")
    print("=" * 70)
    
    planos = ['topo.pdf', 'topo2.pdf']
    
    matcher = TemplateMatcher(
        templates_dir='./templates',
        threshold=0.7
    )
    
    resultados_totales = {}
    
    for plano in planos:
        print(f"\n🔍 Procesando: {plano}")
        results, _, _ = matcher.detect(plano, page_num=0)
        
        resultados_totales[plano] = results['counts']
        
        for material, count in results['counts'].items():
            print(f"  {material}: {count}")
    
    # Agregación
    print(f"\n📈 TOTALES AGREGADOS:")
    materiales_totales = {}
    
    for plano, counts in resultados_totales.items():
        for material, count in counts.items():
            materiales_totales[material] = materiales_totales.get(material, 0) + count
    
    for material, total in materiales_totales.items():
        print(f"  {material}: {total}")
    
    # Guardar resumen
    resumen = {
        'planos_procesados': planos,
        'resultados_individuales': resultados_totales,
        'totales_agregados': materiales_totales
    }
    
    with open('resumen_multiples.json', 'w') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)


def ejemplo_3_ajuste_fino():
    """
    Ejemplo 3: Ajuste fino de parámetros para maximizar precisión
    """
    print("\n" + "=" * 70)
    print("EJEMPLO 3: Ajuste Fino de Parámetros")
    print("=" * 70)
    
    # Configuración para alta precisión
    matcher_precision = TemplateMatcher(
        templates_dir='./templates',
        scales=[0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25],
        angles=[0, 45, 90, 135, 180, 225, 270, 315],
        threshold=0.75,
        nms_iou_threshold=0.35,
        dpi=350
    )
    
    # Configuración para velocidad
    matcher_rapido = TemplateMatcher(
        templates_dir='./templates',
        scales=[0.9, 1.0, 1.1],
        angles=[0, 90, 180],
        threshold=0.65,
        nms_iou_threshold=0.5,
        dpi=200
    )
    
    import time
    
    plano = 'topo.pdf'
    
    # Test precisión
    print("\n🎯 Modo PRECISIÓN:")
    start = time.time()
    results_precision, _, dets_precision = matcher_precision.detect(plano)
    time_precision = time.time() - start
    
    print(f"  Tiempo: {time_precision:.2f}s")
    print(f"  Detecciones: {results_precision['total_detections']}")
    
    # Test velocidad
    print("\n⚡ Modo RÁPIDO:")
    start = time.time()
    results_rapido, _, dets_rapido = matcher_rapido.detect(plano)
    time_rapido = time.time() - start
    
    print(f"  Tiempo: {time_rapido:.2f}s")
    print(f"  Detecciones: {results_rapido['total_detections']}")
    
    print(f"\n📊 Comparación:")
    print(f"  Speedup: {time_precision/time_rapido:.2f}x más rápido (modo rápido)")
    print(f"  Diferencia en detecciones: {abs(results_precision['total_detections'] - results_rapido['total_detections'])}")


def ejemplo_4_integracion_mcp():
    """
    Ejemplo 4: Uso a través de wrapper MCP
    """
    print("\n" + "=" * 70)
    print("EJEMPLO 4: Integración MCP")
    print("=" * 70)
    
    # Inicializar herramienta MCP
    tool = MaterialDetectionTool(templates_dir='./templates')
    
    # Configurar
    init_result = tool.initialize({
        'threshold': 0.7,
        'nms_iou_threshold': 0.4,
        'dpi': 300
    })
    
    print(f"\n✅ Tool inicializada:")
    print(f"  Plantillas cargadas: {init_result['templates_loaded']}")
    print(f"  Materiales disponibles: {', '.join(init_result['materials'])}")
    
    # Método 1: Detección completa con diagnóstico
    print(f"\n🔍 Detección completa con diagnóstico:")
    result = tool.detect_materials(
        pdf_path='topo.pdf',
        page_num=0,
        save_diagnostic=True,
        diagnostic_path='diagnostic_mcp.png'
    )
    
    if result['success']:
        print(f"  ✅ Exitoso")
        print(f"  Total: {result['data']['total_detections']} componentes")
        print(f"  Imagen diagnóstica: {result['diagnostic_image']}")
    else:
        print(f"  ❌ Error: {result['error']}")
    
    # Método 2: Solo conteos (rápido)
    print(f"\n📊 Obtener solo conteos:")
    counts = tool.get_material_count('topo.pdf', page_num=0)
    
    for material, count in counts.items():
        print(f"  {material}: {count}")
    
    # Método 3: Procesamiento por lotes
    print(f"\n📦 Procesamiento por lotes:")
    batch_result = tool.batch_detect(
        pdf_paths=['topo.pdf', 'topo2.pdf'],
        page_num=0
    )
    
    print(f"  PDFs procesados: {batch_result['summary']['total_pdfs']}")
    print(f"  Exitosos: {batch_result['summary']['successful']}")
    print(f"\n  Totales agregados:")
    for material, total in batch_result['summary']['aggregated_counts'].items():
        print(f"    {material}: {total}")


def ejemplo_5_manejo_errores():
    """
    Ejemplo 5: Manejo robusto de errores
    """
    print("\n" + "=" * 70)
    print("EJEMPLO 5: Manejo de Errores")
    print("=" * 70)
    
    tool = MaterialDetectionTool(templates_dir='./templates')
    tool.initialize()
    
    test_cases = [
        ('archivo_inexistente.pdf', 'PDF no existe'),
        ('', 'Path vacío'),
    ]
    
    for pdf_path, descripcion in test_cases:
        print(f"\n🧪 Test: {descripcion}")
        result = tool.detect_materials(pdf_path, page_num=0)
        
        if result['success']:
            print(f"  ✅ Exitoso (inesperado)")
        else:
            print(f"  ❌ Error capturado correctamente")
            print(f"     Tipo: {result.get('error_type')}")
            print(f"     Mensaje: {result.get('error')}")


def ejemplo_6_filtrado_confianza():
    """
    Ejemplo 6: Filtrado por nivel de confianza
    """
    print("\n" + "=" * 70)
    print("EJEMPLO 6: Filtrado por Confianza")
    print("=" * 70)
    
    matcher = TemplateMatcher(
        templates_dir='./templates',
        threshold=0.6  # Umbral bajo para capturar más detecciones
    )
    
    results, _, detections = matcher.detect('topo.pdf')
    
    # Analizar distribución de confianza
    confianzas = [d.confidence for d in detections]
    
    if confianzas:
        import statistics
        
        print(f"\n📊 Estadísticas de Confianza:")
        print(f"  Mínima: {min(confianzas):.3f}")
        print(f"  Máxima: {max(confianzas):.3f}")
        print(f"  Media: {statistics.mean(confianzas):.3f}")
        print(f"  Mediana: {statistics.median(confianzas):.3f}")
        
        # Filtrar por umbrales
        umbrales = [0.7, 0.8, 0.9]
        
        print(f"\n🔍 Detecciones por umbral:")
        for umbral in umbrales:
            count = sum(1 for c in confianzas if c >= umbral)
            print(f"  Confianza >= {umbral}: {count} ({count/len(confianzas)*100:.1f}%)")
        
        # Crear dataset filtrado
        alta_confianza = [d for d in detections if d.confidence >= 0.85]
        
        print(f"\n✨ Detecciones de alta confianza (>= 0.85): {len(alta_confianza)}")
        
        # Guardar solo alta confianza
        results_filtrado = {
            'total_alta_confianza': len(alta_confianza),
            'detections': [
                {
                    'material': d.material,
                    'x': d.x,
                    'y': d.y,
                    'confidence': round(d.confidence, 3)
                }
                for d in alta_confianza
            ]
        }
        
        with open('alta_confianza.json', 'w') as f:
            json.dump(results_filtrado, f, indent=2)


def ejemplo_7_exportacion_coordenadas():
    """
    Ejemplo 7: Exportación de coordenadas para sistemas CAD
    """
    print("\n" + "=" * 70)
    print("EJEMPLO 7: Exportación para CAD")
    print("=" * 70)
    
    matcher = TemplateMatcher(templates_dir='./templates')
    results, image, detections = matcher.detect('topo.pdf')
    
    # Formato DXF simplificado (coordenadas de puntos)
    print(f"\n📐 Generando archivo DXF simplificado...")
    
    dxf_content = []
    dxf_content.append("0\nSECTION\n2\nENTITIES")
    
    for det in detections:
        # Calcular centro del componente
        cx = det.x + det.width / 2
        cy = det.y + det.height / 2
        
        # Convertir coordenadas de píxeles a mm (asumiendo 300 DPI)
        # 1 inch = 25.4 mm, 300 DPI = 300 px/inch
        cx_mm = (cx / 300) * 25.4
        cy_mm = (cy / 300) * 25.4
        
        # Agregar punto
        dxf_content.append(f"0\nPOINT\n8\n{det.material}\n10\n{cx_mm}\n20\n{cy_mm}")
    
    dxf_content.append("0\nENDSEC\n0\nEOF")
    
    with open('componentes.dxf', 'w') as f:
        f.write('\n'.join(dxf_content))
    
    print(f"  ✅ Archivo DXF generado: componentes.dxf")
    print(f"  Capas creadas: {', '.join(set(d.material for d in detections))}")
    
    # CSV alternativo
    print(f"\n📊 Generando archivo CSV...")
    
    with open('componentes.csv', 'w') as f:
        f.write("Material,X_px,Y_px,X_mm,Y_mm,Confidence,Angle\n")
        
        for det in detections:
            cx = det.x + det.width / 2
            cy = det.y + det.height / 2
            cx_mm = (cx / 300) * 25.4
            cy_mm = (cy / 300) * 25.4
            
            f.write(f"{det.material},{cx},{cy},{cx_mm:.2f},{cy_mm:.2f},"
                   f"{det.confidence:.3f},{det.angle}\n")
    
    print(f"  ✅ Archivo CSV generado: componentes.csv")


def menu_principal():
    """Menu interactivo de ejemplos"""
    ejemplos = [
        ("Uso Básico", ejemplo_1_uso_basico),
        ("Múltiples Formatos", ejemplo_2_multiples_formatos),
        ("Ajuste Fino de Parámetros", ejemplo_3_ajuste_fino),
        ("Integración MCP", ejemplo_4_integracion_mcp),
        ("Manejo de Errores", ejemplo_5_manejo_errores),
        ("Filtrado por Confianza", ejemplo_6_filtrado_confianza),
        ("Exportación CAD", ejemplo_7_exportacion_coordenadas),
    ]
    
    print("\n" + "=" * 70)
    print("EJEMPLOS DE USO - COTIZABOT TEMPLATE MATCHING")
    print("=" * 70)
    print("\nSelecciona un ejemplo para ejecutar:\n")
    
    for i, (nombre, _) in enumerate(ejemplos, 1):
        print(f"  {i}. {nombre}")
    
    print(f"  {len(ejemplos) + 1}. Ejecutar TODOS")
    print(f"  0. Salir")
    
    try:
        seleccion = int(input("\nOpción: "))
        
        if seleccion == 0:
            print("\n👋 ¡Hasta luego!")
            return
        
        elif 1 <= seleccion <= len(ejemplos):
            _, funcion = ejemplos[seleccion - 1]
            funcion()
        
        elif seleccion == len(ejemplos) + 1:
            for nombre, funcion in ejemplos:
                try:
                    funcion()
                except Exception as e:
                    print(f"\n⚠️ Error en '{nombre}': {e}")
                    continue
        
        else:
            print("❌ Opción inválida")
    
    except ValueError:
        print("❌ Por favor ingresa un número")
    except KeyboardInterrupt:
        print("\n\n👋 Interrumpido por usuario")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == '__main__':
    # Ejecutar menu interactivo
    # O descomentar para ejecutar ejemplo específico:
    
    # ejemplo_1_uso_basico()
    # ejemplo_4_integracion_mcp()
    
    menu_principal()
