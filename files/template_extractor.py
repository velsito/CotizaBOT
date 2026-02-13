"""
Template Extractor - Herramienta para crear biblioteca de plantillas
Permite extraer y guardar íconos de componentes desde planos de referencia
"""

import cv2
import numpy as np
import fitz
from pathlib import Path


class TemplateExtractor:
    """
    Herramienta interactiva para extraer plantillas de componentes desde PDFs
    """
    
    def __init__(self, output_dir: str = "./templates", dpi: int = 300):
        """
        Args:
            output_dir: Carpeta donde guardar las plantillas
            dpi: Resolución para conversión de PDF
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.dpi = dpi
        
    def pdf_to_image(self, pdf_path: str, page_num: int = 0) -> np.ndarray:
        """Convierte PDF a imagen en escala de grises"""
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        
        zoom = self.dpi / 72
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        doc.close()
        
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        
        return img
    
    def extract_roi_interactive(self, pdf_path: str, page_num: int = 0):
        """
        Permite seleccionar ROIs (regiones de interés) interactivamente
        
        Instrucciones:
        - Click y arrastra para seleccionar área
        - Presiona 's' para guardar la selección
        - Presiona 'r' para resetear
        - Presiona 'q' para salir
        """
        image = self.pdf_to_image(pdf_path, page_num)
        display_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        
        # Variables para selección
        roi_list = []
        selecting = False
        start_point = None
        end_point = None
        
        def mouse_callback(event, x, y, flags, param):
            nonlocal selecting, start_point, end_point, display_image
            
            if event == cv2.EVENT_LBUTTONDOWN:
                selecting = True
                start_point = (x, y)
                
            elif event == cv2.EVENT_MOUSEMOVE:
                if selecting:
                    end_point = (x, y)
                    temp_img = display_image.copy()
                    cv2.rectangle(temp_img, start_point, end_point, (0, 255, 0), 2)
                    cv2.imshow('Template Extractor', temp_img)
                    
            elif event == cv2.EVENT_LBUTTONUP:
                selecting = False
                end_point = (x, y)
        
        cv2.namedWindow('Template Extractor', cv2.WINDOW_NORMAL)
        cv2.setMouseCallback('Template Extractor', mouse_callback)
        
        print("\n🎯 Modo de extracción interactivo")
        print("Instrucciones:")
        print("  - Click y arrastra para seleccionar componente")
        print("  - 's' = Guardar plantilla")
        print("  - 'r' = Resetear selección")
        print("  - 'q' = Salir")
        
        template_count = 0
        
        while True:
            cv2.imshow('Template Extractor', display_image)
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('q'):
                break
                
            elif key == ord('r'):
                display_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
                start_point = None
                end_point = None
                
            elif key == ord('s') and start_point and end_point:
                # Extraer ROI
                x1 = min(start_point[0], end_point[0])
                y1 = min(start_point[1], end_point[1])
                x2 = max(start_point[0], end_point[0])
                y2 = max(start_point[1], end_point[1])
                
                if x2 - x1 > 5 and y2 - y1 > 5:
                    roi = image[y1:y2, x1:x2]
                    
                    # Solicitar nombre
                    print(f"\n📦 ROI extraído: {roi.shape[1]}x{roi.shape[0]} px")
                    material = input("Nombre del material (ej: fusible, luminaria): ").strip()
                    
                    if material:
                        # Determinar versión
                        existing = list(self.output_dir.glob(f"{material}_v*.png"))
                        version = len(existing) + 1
                        
                        filename = f"{material}_v{version}.png"
                        filepath = self.output_dir / filename
                        
                        cv2.imwrite(str(filepath), roi)
                        print(f"✅ Guardado: {filepath}")
                        template_count += 1
                        
                        # Marcar en imagen como guardado
                        cv2.rectangle(display_image, (x1, y1), (x2, y2), (0, 0, 255), 2)
                        cv2.putText(display_image, material, (x1, y1-5),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
                    
                    start_point = None
                    end_point = None
        
        cv2.destroyAllWindows()
        print(f"\n✨ {template_count} plantillas creadas")
    
    def extract_batch_from_coordinates(
        self,
        pdf_path: str,
        extractions: list,
        page_num: int = 0
    ):
        """
        Extrae múltiples plantillas usando coordenadas predefinidas
        
        Args:
            pdf_path: Ruta al PDF
            extractions: Lista de dicts con formato:
                [
                    {'material': 'fusible', 'x': 100, 'y': 200, 'w': 50, 'h': 30},
                    ...
                ]
            page_num: Número de página
        """
        image = self.pdf_to_image(pdf_path, page_num)
        
        for idx, extraction in enumerate(extractions, 1):
            material = extraction['material']
            x, y = extraction['x'], extraction['y']
            w, h = extraction['w'], extraction['h']
            
            roi = image[y:y+h, x:x+w]
            
            # Determinar versión
            existing = list(self.output_dir.glob(f"{material}_v*.png"))
            version = len(existing) + 1
            
            filename = f"{material}_v{version}.png"
            filepath = self.output_dir / filename
            
            cv2.imwrite(str(filepath), roi)
            print(f"✅ {idx}/{len(extractions)} - Guardado: {filepath} ({w}x{h} px)")
    
    def create_rotated_variants(self, template_path: str, angles: list = None):
        """
        Crea variantes rotadas de una plantilla existente
        
        Args:
            template_path: Ruta a plantilla PNG
            angles: Lista de ángulos (default: [90, 180, 270])
        """
        angles = angles or [90, 180, 270]
        
        template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise ValueError(f"No se pudo cargar: {template_path}")
        
        path = Path(template_path)
        base_name = path.stem  # ej: "fusible_v1"
        
        for angle in angles:
            # Rotar
            h, w = template.shape
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            
            cos = np.abs(M[0, 0])
            sin = np.abs(M[0, 1])
            new_w = int((h * sin) + (w * cos))
            new_h = int((h * cos) + (w * sin))
            
            M[0, 2] += (new_w / 2) - center[0]
            M[1, 2] += (new_h / 2) - center[1]
            
            rotated = cv2.warpAffine(template, M, (new_w, new_h),
                                      borderValue=255,
                                      flags=cv2.INTER_CUBIC)
            
            # Guardar con sufijo de ángulo
            output_name = f"{base_name}_rot{angle}.png"
            output_path = path.parent / output_name
            
            cv2.imwrite(str(output_path), rotated)
            print(f"✅ Variante rotada guardada: {output_path}")


def main():
    """Script de ejemplo"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Extractor de plantillas')
    parser.add_argument('pdf_path', help='Ruta al PDF de referencia')
    parser.add_argument('--mode', choices=['interactive', 'batch'],
                       default='interactive', help='Modo de extracción')
    parser.add_argument('--page', type=int, default=0, help='Número de página')
    parser.add_argument('--output', default='./templates', help='Carpeta de salida')
    
    args = parser.parse_args()
    
    extractor = TemplateExtractor(output_dir=args.output)
    
    if args.mode == 'interactive':
        extractor.extract_roi_interactive(args.pdf_path, args.page)
    
    elif args.mode == 'batch':
        # Ejemplo de extracción por lotes
        # Estas coordenadas deben ser ajustadas según tu PDF
        extractions = [
            {'material': 'fusible', 'x': 100, 'y': 200, 'w': 40, 'h': 20},
            {'material': 'luminaria', 'x': 300, 'y': 400, 'w': 30, 'h': 30},
        ]
        extractor.extract_batch_from_coordinates(args.pdf_path, extractions, args.page)


if __name__ == '__main__':
    main()
