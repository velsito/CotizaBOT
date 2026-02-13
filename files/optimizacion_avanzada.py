"""
Guía de Optimización Avanzada
Tips y técnicas para maximizar precisión y rendimiento
"""

# ============================================================================
# OPTIMIZACIÓN DE PLANTILLAS
# ============================================================================

"""
1. PREPROCESAMIENTO DE PLANTILLAS

Las plantillas de alta calidad son críticas para el éxito del sistema.

Técnicas recomendadas:
"""

import cv2
import numpy as np


def optimizar_plantilla(template_path: str, output_path: str):
    """
    Aplica preprocesamiento a una plantilla para mejorar matching
    """
    img = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    
    # 1. Binarización adaptativa (útil para plantillas con variación de iluminación)
    img_binary = cv2.adaptiveThreshold(
        img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 11, 2
    )
    
    # 2. Reducción de ruido
    img_denoised = cv2.fastNlMeansDenoising(img_binary, None, 10, 7, 21)
    
    # 3. Morfología para limpiar bordes
    kernel = np.ones((3, 3), np.uint8)
    img_clean = cv2.morphologyEx(img_denoised, cv2.MORPH_CLOSE, kernel)
    
    # 4. Normalizar contraste
    img_normalized = cv2.normalize(img_clean, None, 0, 255, cv2.NORM_MINMAX)
    
    cv2.imwrite(output_path, img_normalized)
    
    print(f"✅ Plantilla optimizada: {output_path}")
    return img_normalized


"""
2. TÉCNICA DE EDGE MATCHING

Para componentes con formas distintivas, usar detección de bordes
puede mejorar la robustez frente a variaciones de relleno.
"""

def crear_plantilla_edges(template_path: str, output_path: str):
    """
    Crea versión basada en edges de una plantilla
    """
    img = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
    
    # Detección de bordes con Canny
    edges = cv2.Canny(img, 50, 150)
    
    # Dilatar ligeramente para hacer bordes más robustos
    kernel = np.ones((2, 2), np.uint8)
    edges_dilated = cv2.dilate(edges, kernel, iterations=1)
    
    cv2.imwrite(output_path, edges_dilated)
    print(f"✅ Plantilla de edges: {output_path}")
    

# ============================================================================
# OPTIMIZACIÓN DE RENDIMIENTO
# ============================================================================

"""
3. BÚSQUEDA PIRAMIDAL

Acelera matching buscando primero en imagen downsampled,
luego refinando en área de interés.
"""

def template_match_piramidal(image, template, scales, threshold):
    """
    Búsqueda multiescala optimizada usando pirámide
    """
    detections = []
    
    # Nivel 1: Búsqueda rápida en imagen reducida
    image_small = cv2.resize(image, None, fx=0.5, fy=0.5)
    template_small = cv2.resize(template, None, fx=0.5, fy=0.5)
    
    result_small = cv2.matchTemplate(image_small, template_small, cv2.TM_CCOEFF_NORMED)
    locations_small = np.where(result_small >= threshold - 0.1)  # Umbral más bajo
    
    # Nivel 2: Refinar en regiones de interés en imagen completa
    for y_small, x_small in zip(*locations_small):
        # Convertir a coordenadas de imagen completa
        x = x_small * 2
        y = y_small * 2
        
        # Extraer ROI ampliada
        margin = 20
        roi = image[
            max(0, y-margin):min(image.shape[0], y+template.shape[0]+margin),
            max(0, x-margin):min(image.shape[1], x+template.shape[1]+margin)
        ]
        
        if roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
            continue
        
        # Matching refinado
        result_roi = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        
        # ... procesar resultado
    
    return detections


"""
4. PARALELIZACIÓN

Procesar múltiples páginas o plantillas en paralelo.
"""

from concurrent.futures import ProcessPoolExecutor, as_completed


def procesar_plano_paralelo(pdf_path, page_num, templates_dir):
    """Función worker para procesamiento paralelo"""
    from template_matcher import TemplateMatcher
    
    matcher = TemplateMatcher(templates_dir=templates_dir)
    results, _, _ = matcher.detect(pdf_path, page_num)
    return results


def procesar_lote_paralelo(pdf_paths, templates_dir, max_workers=4):
    """
    Procesa múltiples PDFs en paralelo
    """
    resultados = {}
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Enviar trabajos
        futures = {
            executor.submit(procesar_plano_paralelo, pdf, 0, templates_dir): pdf
            for pdf in pdf_paths
        }
        
        # Recolectar resultados
        for future in as_completed(futures):
            pdf_path = futures[future]
            try:
                resultado = future.result()
                resultados[pdf_path] = resultado
                print(f"✅ Completado: {pdf_path}")
            except Exception as e:
                print(f"❌ Error en {pdf_path}: {e}")
                resultados[pdf_path] = {'error': str(e)}
    
    return resultados


# ============================================================================
# TÉCNICAS AVANZADAS DE DETECCIÓN
# ============================================================================

"""
5. TEMPLATE MATCHING CON FEATURES (SIFT/ORB)

Para componentes complejos, combinar template matching con
feature matching puede mejorar robustez.
"""

def feature_matching_sift(image, template, threshold=0.7):
    """
    Detección usando SIFT features (más robusto pero más lento)
    """
    # Inicializar SIFT
    sift = cv2.SIFT_create()
    
    # Detectar keypoints y descriptores
    kp1, des1 = sift.detectAndCompute(template, None)
    kp2, des2 = sift.detectAndCompute(image, None)
    
    if des1 is None or des2 is None:
        return []
    
    # Matching con FLANN
    FLANN_INDEX_KDTREE = 1
    index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    search_params = dict(checks=50)
    
    flann = cv2.FlannBasedMatcher(index_params, search_params)
    matches = flann.knnMatch(des1, des2, k=2)
    
    # Filtrar buenos matches (Lowe's ratio test)
    good_matches = []
    for m, n in matches:
        if m.distance < 0.7 * n.distance:
            good_matches.append(m)
    
    # Si hay suficientes matches, calcular homografía
    if len(good_matches) > 10:
        src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        
        M, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
        
        if M is not None:
            # Transformar corners de template para obtener ubicación
            h, w = template.shape
            pts = np.float32([[0, 0], [0, h-1], [w-1, h-1], [w-1, 0]]).reshape(-1, 1, 2)
            dst = cv2.perspectiveTransform(pts, M)
            
            # Calcular bounding box
            x, y, w, h = cv2.boundingRect(dst)
            
            return [(x, y, w, h, len(good_matches) / len(kp1))]
    
    return []


"""
6. APRENDIZAJE AUTOMÁTICO DE THRESHOLD

Determinar threshold óptimo automáticamente basado en validación.
"""

def calibrar_threshold_automatico(matcher, pdf_validacion, ground_truth):
    """
    Encuentra threshold óptimo comparando contra ground truth
    
    Args:
        matcher: TemplateMatcher instance
        pdf_validacion: PDF con conteos conocidos
        ground_truth: Dict con conteos reales {'fusible': 10, 'luminaria': 25}
    
    Returns:
        Threshold óptimo
    """
    thresholds = np.arange(0.5, 0.95, 0.05)
    best_threshold = 0.7
    best_error = float('inf')
    
    print("🔍 Calibrando threshold...")
    
    for thresh in thresholds:
        matcher.threshold = thresh
        results, _, _ = matcher.detect(pdf_validacion)
        
        # Calcular error absoluto medio
        error = sum(
            abs(results['counts'].get(material, 0) - count)
            for material, count in ground_truth.items()
        ) / len(ground_truth)
        
        print(f"  Threshold {thresh:.2f}: error = {error:.2f}")
        
        if error < best_error:
            best_error = error
            best_threshold = thresh
    
    print(f"\n✅ Threshold óptimo: {best_threshold:.2f} (error: {best_error:.2f})")
    return best_threshold


# ============================================================================
# ANÁLISIS POST-DETECCIÓN
# ============================================================================

"""
7. CLUSTERING ESPACIAL

Identificar grupos de componentes (ej. paneles eléctricos)
"""

from sklearn.cluster import DBSCAN


def analizar_clusters(detections, eps=50, min_samples=3):
    """
    Agrupa detecciones espacialmente cercanas
    
    Args:
        detections: Lista de Detection objects
        eps: Radio máximo entre puntos de un cluster (píxeles)
        min_samples: Mínimo de puntos para formar cluster
    """
    if not detections:
        return []
    
    # Extraer coordenadas centrales
    coords = np.array([
        [d.x + d.width/2, d.y + d.height/2] 
        for d in detections
    ])
    
    # Clustering
    clustering = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
    
    # Agrupar por cluster
    clusters = {}
    for idx, label in enumerate(clustering.labels_):
        if label == -1:  # Ruido
            continue
        
        if label not in clusters:
            clusters[label] = []
        
        clusters[label].append(detections[idx])
    
    print(f"📍 Encontrados {len(clusters)} clusters de componentes")
    
    for cluster_id, items in clusters.items():
        materials = [d.material for d in items]
        print(f"  Cluster {cluster_id}: {len(items)} componentes")
        print(f"    Materiales: {', '.join(set(materials))}")
    
    return clusters


"""
8. VALIDACIÓN DE COHERENCIA

Verificar que detecciones tengan sentido físico
"""

def validar_coherencia(detections, rules):
    """
    Valida detecciones contra reglas de diseño eléctrico
    
    Args:
        detections: Lista de detecciones
        rules: Dict con reglas de validación
            {
                'min_distance': {'fusible': 30},  # Mínima distancia entre fusibles
                'max_count': {'fusible': 50},      # Máximo esperado
                'required_pairs': [('fusible', 'interruptor')]  # Debe haber ambos
            }
    """
    warnings = []
    
    # Validar distancia mínima
    if 'min_distance' in rules:
        for material, min_dist in rules['min_distance'].items():
            material_dets = [d for d in detections if d.material == material]
            
            for i, det1 in enumerate(material_dets):
                for det2 in material_dets[i+1:]:
                    dist = np.sqrt((det1.x - det2.x)**2 + (det1.y - det2.y)**2)
                    
                    if dist < min_dist:
                        warnings.append(
                            f"⚠️ Dos {material}s muy cercanos: distancia {dist:.0f}px "
                            f"(mínimo: {min_dist}px)"
                        )
    
    # Validar conteos máximos
    if 'max_count' in rules:
        counts = {}
        for det in detections:
            counts[det.material] = counts.get(det.material, 0) + 1
        
        for material, max_count in rules['max_count'].items():
            if counts.get(material, 0) > max_count:
                warnings.append(
                    f"⚠️ Demasiados {material}s: {counts[material]} "
                    f"(máximo esperado: {max_count})"
                )
    
    # Validar pares requeridos
    if 'required_pairs' in rules:
        materials_found = set(d.material for d in detections)
        
        for mat1, mat2 in rules['required_pairs']:
            if mat1 in materials_found and mat2 not in materials_found:
                warnings.append(
                    f"⚠️ Encontrado {mat1} pero falta {mat2}"
                )
    
    return warnings


# ============================================================================
# EJEMPLO DE PIPELINE COMPLETO OPTIMIZADO
# ============================================================================

def pipeline_completo_optimizado(pdf_path, templates_dir):
    """
    Pipeline end-to-end con todas las optimizaciones
    """
    from template_matcher import TemplateMatcher
    
    print("🚀 Pipeline Optimizado")
    print("=" * 70)
    
    # 1. Inicializar con configuración balanceada
    print("\n1️⃣ Inicializando detector...")
    matcher = TemplateMatcher(
        templates_dir=templates_dir,
        scales=[0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15],  # 7 escalas
        angles=[0, 90, 180, 270],
        threshold=0.7,
        nms_iou_threshold=0.4,
        dpi=300
    )
    
    # 2. Detección
    print("\n2️⃣ Ejecutando detección...")
    results, image, detections = matcher.detect(pdf_path)
    
    print(f"   ✅ {results['total_detections']} componentes detectados")
    
    # 3. Análisis de confianza
    print("\n3️⃣ Analizando distribución de confianza...")
    confidences = [d.confidence for d in detections]
    if confidences:
        import statistics
        print(f"   Media: {statistics.mean(confidences):.3f}")
        print(f"   Mediana: {statistics.median(confidences):.3f}")
        
        # Filtrar baja confianza
        alta_conf = [d for d in detections if d.confidence >= 0.75]
        print(f"   Alta confianza (>=0.75): {len(alta_conf)} ({len(alta_conf)/len(detections)*100:.1f}%)")
    
    # 4. Clustering espacial
    print("\n4️⃣ Analizando clustering espacial...")
    clusters = analizar_clusters(detections, eps=100, min_samples=2)
    
    # 5. Validación de coherencia
    print("\n5️⃣ Validando coherencia...")
    reglas = {
        'min_distance': {'fusible': 25},
        'max_count': {'fusible': 100, 'luminaria': 200}
    }
    warnings = validar_coherencia(detections, reglas)
    
    if warnings:
        print("   ⚠️ Advertencias encontradas:")
        for w in warnings[:5]:  # Mostrar primeras 5
            print(f"      {w}")
    else:
        print("   ✅ Sin advertencias de coherencia")
    
    # 6. Exportar resultados
    print("\n6️⃣ Exportando resultados...")
    
    # JSON enriquecido
    output = {
        **results,
        'confidence_stats': {
            'mean': statistics.mean(confidences) if confidences else 0,
            'median': statistics.median(confidences) if confidences else 0,
            'min': min(confidences) if confidences else 0,
            'max': max(confidences) if confidences else 0
        },
        'clusters_found': len(clusters),
        'validation_warnings': warnings
    }
    
    import json
    with open('resultados_optimizados.json', 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    # Visualización
    matcher.visualize_detections(image, detections, 'diagnostico_optimizado.png')
    
    print("\n✅ Pipeline completado")
    print("   📄 resultados_optimizados.json")
    print("   🖼️ diagnostico_optimizado.png")
    
    return output


# ============================================================================
# USO
# ============================================================================

if __name__ == '__main__':
    # Ejemplo 1: Optimizar plantilla
    # optimizar_plantilla('templates/fusible_v1.png', 'templates/fusible_v1_opt.png')
    
    # Ejemplo 2: Pipeline completo
    # resultado = pipeline_completo_optimizado('topo.pdf', './templates')
    
    # Ejemplo 3: Procesamiento paralelo
    # pdfs = ['topo.pdf', 'topo2.pdf', 'topo3.pdf']
    # resultados = procesar_lote_paralelo(pdfs, './templates', max_workers=4)
    
    print(__doc__)
