"""
CotizaBOT - Template Matching Engine
Detección robusta de componentes eléctricos en planos PDF usando Computer Vision
"""

import cv2
import numpy as np
import fitz  # PyMuPDF
from pathlib import Path
from typing import List, Dict, Tuple
import json
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class Detection:
    """Clase para almacenar información de una detección"""
    material: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    angle: int
    scale: float
    
    def to_dict(self):
        return asdict(self)
    
    def get_bbox(self) -> Tuple[int, int, int, int]:
        """Retorna bounding box como (x1, y1, x2, y2)"""
        return (self.x, self.y, self.x + self.width, self.y + self.height)


class TemplateMatcher:
    """
    Motor de detección de componentes con Template Matching multiescala y multiorientación
    """
    
    def __init__(
        self,
        templates_dir: str,
        scales: List[float] = None,
        angles: List[int] = None,
        threshold: float = 0.7,
        nms_iou_threshold: float = 0.4,
        dpi: int = 300
    ):
        """
        Args:
            templates_dir: Ruta a la carpeta con plantillas PNG
            scales: Lista de escalas a probar (ej. [0.8, 0.9, 1.0, 1.1, 1.2])
            angles: Lista de ángulos de rotación (ej. [0, 90, 180, 270])
            threshold: Umbral de confianza para template matching (0-1)
            nms_iou_threshold: Umbral IoU para Non-Maximum Suppression
            dpi: DPI para conversión de PDF a imagen
        """
        self.templates_dir = Path(templates_dir)
        self.scales = scales or [0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2]
        self.angles = angles or [0, 90, 180, 270]
        self.threshold = threshold
        self.nms_iou_threshold = nms_iou_threshold
        self.dpi = dpi
        
        # Cargar plantillas
        self.templates = self._load_templates()
        
    def _load_templates(self) -> Dict[str, List[np.ndarray]]:
        """
        Carga todas las plantillas PNG de la carpeta
        
        Returns:
            Dict con material como key y lista de plantillas como value
            Ej: {'fusible': [img1, img2], 'luminaria': [img1]}
        """
        templates = defaultdict(list)
        
        if not self.templates_dir.exists():
            raise FileNotFoundError(f"Carpeta de plantillas no encontrada: {self.templates_dir}")
        
        for template_path in sorted(self.templates_dir.glob("*.png")):
            # Extraer nombre del material del archivo
            # Ej: "fusible_v1.png" -> "fusible"
            material_name = template_path.stem.rsplit('_v', 1)[0]
            
            # Cargar imagen en escala de grises
            img = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
            
            if img is None:
                print(f"⚠️ No se pudo cargar: {template_path}")
                continue
                
            templates[material_name].append(img)
            print(f"✓ Plantilla cargada: {template_path.name} ({img.shape[1]}x{img.shape[0]})")
        
        print(f"\n📦 Total: {sum(len(v) for v in templates.values())} plantillas de {len(templates)} materiales")
        return dict(templates)
    
    def _rotate_template(self, template: np.ndarray, angle: int) -> np.ndarray:
        """
        Rota una plantilla sin recortar
        
        Args:
            template: Imagen a rotar
            angle: Ángulo en grados
            
        Returns:
            Imagen rotada con fondo expandido
        """
        if angle == 0:
            return template
        
        h, w = template.shape[:2]
        center = (w // 2, h // 2)
        
        # Matriz de rotación
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        
        # Calcular nuevo tamaño para no recortar
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        new_w = int((h * sin) + (w * cos))
        new_h = int((h * cos) + (w * sin))
        
        # Ajustar matriz de traslación
        M[0, 2] += (new_w / 2) - center[0]
        M[1, 2] += (new_h / 2) - center[1]
        
        # Rotar con fondo blanco (255) para no interferir con matching
        rotated = cv2.warpAffine(template, M, (new_w, new_h), 
                                  borderValue=255, 
                                  flags=cv2.INTER_CUBIC)
        
        return rotated
    
    def _scale_template(self, template: np.ndarray, scale: float) -> np.ndarray:
        """Escala una plantilla"""
        if scale == 1.0:
            return template
        
        new_w = int(template.shape[1] * scale)
        new_h = int(template.shape[0] * scale)
        
        if new_w < 10 or new_h < 10:
            return None
        
        return cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    
    def _calculate_iou(self, box1: Tuple, box2: Tuple) -> float:
        """
        Calcula IoU (Intersection over Union) entre dos bounding boxes
        
        Args:
            box1, box2: Tuplas (x1, y1, x2, y2)
            
        Returns:
            Valor IoU entre 0 y 1
        """
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        # Área de intersección
        x_left = max(x1_1, x1_2)
        y_top = max(y1_1, y1_2)
        x_right = min(x2_1, x2_2)
        y_bottom = min(y2_1, y2_2)
        
        if x_right < x_left or y_bottom < y_top:
            return 0.0
        
        intersection_area = (x_right - x_left) * (y_bottom - y_top)
        
        # Área de unión
        box1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
        box2_area = (x2_2 - x1_2) * (y2_2 - y1_2)
        union_area = box1_area + box2_area - intersection_area
        
        return intersection_area / union_area if union_area > 0 else 0.0
    
    def _non_maximum_suppression(self, detections: List[Detection]) -> List[Detection]:
        """
        Aplica Non-Maximum Suppression para eliminar detecciones duplicadas
        
        Args:
            detections: Lista de detecciones
            
        Returns:
            Lista filtrada de detecciones
        """
        if not detections:
            return []
        
        # Ordenar por confianza (mayor primero)
        detections = sorted(detections, key=lambda d: d.confidence, reverse=True)
        
        keep = []
        
        while detections:
            # Tomar la detección con mayor confianza
            best = detections.pop(0)
            keep.append(best)
            
            # Filtrar detecciones con alta superposición
            best_bbox = best.get_bbox()
            filtered = []
            
            for det in detections:
                iou = self._calculate_iou(best_bbox, det.get_bbox())
                
                # Mantener solo si IoU es bajo (no se superponen mucho)
                if iou < self.nms_iou_threshold:
                    filtered.append(det)
            
            detections = filtered
        
        return keep
    
    def _match_template_variants(
        self, 
        image: np.ndarray, 
        template: np.ndarray,
        material: str
    ) -> List[Detection]:
        """
        Busca una plantilla con todas sus variaciones de escala y rotación
        
        Args:
            image: Imagen donde buscar
            template: Plantilla original
            material: Nombre del material
            
        Returns:
            Lista de detecciones antes de NMS
        """
        detections = []
        
        for angle in self.angles:
            # Rotar plantilla
            rotated = self._rotate_template(template, angle)
            
            for scale in self.scales:
                # Escalar plantilla rotada
                scaled = self._scale_template(rotated, scale)
                
                if scaled is None:
                    continue
                
                # Validar dimensiones
                if scaled.shape[0] > image.shape[0] or scaled.shape[1] > image.shape[1]:
                    continue
                
                # Template Matching con normalización
                result = cv2.matchTemplate(image, scaled, cv2.TM_CCOEFF_NORMED)
                
                # Encontrar ubicaciones sobre el umbral
                locations = np.where(result >= self.threshold)
                
                for pt in zip(*locations[::-1]):  # (x, y)
                    detections.append(Detection(
                        material=material,
                        x=int(pt[0]),
                        y=int(pt[1]),
                        width=scaled.shape[1],
                        height=scaled.shape[0],
                        confidence=float(result[pt[1], pt[0]]),
                        angle=angle,
                        scale=scale
                    ))
        
        return detections
    
    def pdf_to_image(self, pdf_path: str, page_num: int = 0) -> np.ndarray:
        """
        Convierte una página de PDF a imagen en escala de grises
        
        Args:
            pdf_path: Ruta al archivo PDF
            page_num: Número de página (0-indexed)
            
        Returns:
            Imagen en escala de grises (numpy array)
        """
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        
        # Convertir a imagen con DPI especificado
        zoom = self.dpi / 72  # 72 DPI es el estándar de PDF
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Convertir a numpy array
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        
        doc.close()
        
        # Convertir a escala de grises si es necesario
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        
        return img
    
    def detect(self, pdf_path: str, page_num: int = 0) -> Dict:
        """
        Ejecuta detección completa en un PDF
        
        Args:
            pdf_path: Ruta al archivo PDF
            page_num: Número de página a analizar
            
        Returns:
            Dict con resultados en formato JSON-serializable
        """
        print(f"\n🔍 Procesando: {pdf_path} (página {page_num})")
        
        # Convertir PDF a imagen
        image = self.pdf_to_image(pdf_path, page_num)
        print(f"📄 Imagen generada: {image.shape[1]}x{image.shape[0]} px")
        
        all_detections = []
        
        # Procesar cada material y sus plantillas
        for material, templates in self.templates.items():
            print(f"\n🔎 Buscando: {material}")
            material_detections = []
            
            for idx, template in enumerate(templates, 1):
                print(f"  Plantilla {idx}/{len(templates)}... ", end="")
                
                # Buscar con todas las variaciones
                dets = self._match_template_variants(image, template, material)
                material_detections.extend(dets)
                
                print(f"{len(dets)} coincidencias brutas")
            
            # Aplicar NMS por material
            if material_detections:
                filtered = self._non_maximum_suppression(material_detections)
                all_detections.extend(filtered)
                print(f"  ✓ {len(filtered)} detecciones después de NMS")
            else:
                print(f"  ✗ No se encontraron coincidencias")
        
        # Agrupar por material
        results_by_material = defaultdict(list)
        for det in all_detections:
            results_by_material[det.material].append({
                'x': det.x,
                'y': det.y,
                'confidence': round(det.confidence, 3),
                'angle': det.angle,
                'scale': round(det.scale, 2)
            })
        
        # Preparar resultado final
        results = {
            'pdf_path': pdf_path,
            'page': page_num,
            'image_size': {'width': int(image.shape[1]), 'height': int(image.shape[0])},
            'total_detections': len(all_detections),
            'detections_by_material': dict(results_by_material),
            'counts': {material: len(dets) for material, dets in results_by_material.items()}
        }
        
        print(f"\n✅ Total detectado: {len(all_detections)} componentes")
        for material, count in results['counts'].items():
            print(f"   • {material}: {count}")
        
        return results, image, all_detections
    
    def visualize_detections(
        self, 
        image: np.ndarray, 
        detections: List[Detection],
        output_path: str
    ):
        """
        Genera imagen de diagnóstico con bounding boxes coloreados
        
        Args:
            image: Imagen original en escala de grises
            detections: Lista de detecciones
            output_path: Ruta para guardar imagen
        """
        # Convertir a BGR para dibujar en color
        vis_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        
        # Colores por material (BGR)
        colors = {
            'fusible': (0, 0, 255),      # Rojo
            'luminaria': (0, 255, 0),    # Verde
            'interruptor': (255, 0, 0),  # Azul
            'tomacorriente': (0, 255, 255), # Amarillo
            'default': (255, 0, 255)     # Magenta
        }
        
        for det in detections:
            color = colors.get(det.material, colors['default'])
            
            # Dibujar rectángulo
            cv2.rectangle(
                vis_image,
                (det.x, det.y),
                (det.x + det.width, det.y + det.height),
                color,
                2
            )
            
            # Etiqueta con fondo
            label = f"{det.material} ({det.confidence:.2f})"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness = 1
            
            (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, thickness)
            
            # Fondo blanco para el texto
            cv2.rectangle(
                vis_image,
                (det.x, det.y - text_h - 5),
                (det.x + text_w, det.y),
                (255, 255, 255),
                -1
            )
            
            # Texto
            cv2.putText(
                vis_image,
                label,
                (det.x, det.y - 5),
                font,
                font_scale,
                color,
                thickness
            )
        
        # Guardar
        cv2.imwrite(output_path, vis_image)
        print(f"\n💾 Imagen de diagnóstico guardada: {output_path}")


def main():
    """Script de prueba"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Template Matching para planos eléctricos')
    parser.add_argument('pdf_path', help='Ruta al archivo PDF')
    parser.add_argument('--templates', default='./templates', help='Carpeta de plantillas')
    parser.add_argument('--page', type=int, default=0, help='Número de página')
    parser.add_argument('--threshold', type=float, default=0.7, help='Umbral de confianza')
    parser.add_argument('--nms-iou', type=float, default=0.4, help='Umbral IoU para NMS')
    parser.add_argument('--output-json', default='./detections.json', help='Archivo de salida JSON')
    parser.add_argument('--output-image', default='./diagnostic.png', help='Imagen de diagnóstico')
    
    args = parser.parse_args()
    
    # Crear detector
    matcher = TemplateMatcher(
        templates_dir=args.templates,
        threshold=args.threshold,
        nms_iou_threshold=args.nms_iou
    )
    
    # Ejecutar detección
    results, image, detections = matcher.detect(args.pdf_path, args.page)
    
    # Guardar JSON
    with open(args.output_json, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"💾 Resultados guardados: {args.output_json}")
    
    # Guardar visualización
    matcher.visualize_detections(image, detections, args.output_image)
    
    print("\n✨ Proceso completado exitosamente")


if __name__ == '__main__':
    main()
