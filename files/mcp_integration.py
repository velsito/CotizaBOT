"""
MCP Tool Wrapper para Template Matching
Módulo listo para integrar en servidor MCP de CotizaBOT
"""

from typing import Dict, Any
import json
from pathlib import Path
from template_matcher import TemplateMatcher


class MaterialDetectionTool:
    """
    Herramienta MCP para detección de materiales en planos eléctricos
    """
    
    def __init__(self, templates_dir: str = "./templates"):
        """
        Args:
            templates_dir: Carpeta con plantillas PNG organizadas por material
        """
        self.templates_dir = templates_dir
        self.matcher = None
        
    def initialize(self, config: Dict[str, Any] = None):
        """
        Inicializa el matcher con configuración personalizada
        
        Args:
            config: Diccionario con parámetros opcionales:
                - threshold: float (default 0.7)
                - nms_iou_threshold: float (default 0.4)
                - scales: List[float]
                - angles: List[int]
                - dpi: int (default 300)
        """
        config = config or {}
        
        self.matcher = TemplateMatcher(
            templates_dir=self.templates_dir,
            threshold=config.get('threshold', 0.7),
            nms_iou_threshold=config.get('nms_iou_threshold', 0.4),
            scales=config.get('scales'),
            angles=config.get('angles'),
            dpi=config.get('dpi', 300)
        )
        
        return {
            'status': 'initialized',
            'templates_loaded': sum(len(v) for v in self.matcher.templates.values()),
            'materials': list(self.matcher.templates.keys())
        }
    
    def detect_materials(
        self, 
        pdf_path: str, 
        page_num: int = 0,
        save_diagnostic: bool = False,
        diagnostic_path: str = None
    ) -> Dict[str, Any]:
        """
        Detecta materiales en un plano PDF
        
        Args:
            pdf_path: Ruta al archivo PDF
            page_num: Número de página a analizar
            save_diagnostic: Si True, guarda imagen de diagnóstico
            diagnostic_path: Ruta para imagen de diagnóstico
            
        Returns:
            Dict con estructura:
            {
                'success': bool,
                'data': {
                    'pdf_path': str,
                    'page': int,
                    'total_detections': int,
                    'counts': {'material': count},
                    'detections_by_material': {
                        'material': [
                            {'x': int, 'y': int, 'confidence': float, ...}
                        ]
                    }
                },
                'diagnostic_image': str | None
            }
        """
        if self.matcher is None:
            self.initialize()
        
        try:
            # Ejecutar detección
            results, image, detections = self.matcher.detect(pdf_path, page_num)
            
            # Guardar diagnóstico si se solicita
            diagnostic_saved = None
            if save_diagnostic:
                if diagnostic_path is None:
                    diagnostic_path = f"./diagnostic_{Path(pdf_path).stem}_p{page_num}.png"
                
                self.matcher.visualize_detections(image, detections, diagnostic_path)
                diagnostic_saved = diagnostic_path
            
            return {
                'success': True,
                'data': results,
                'diagnostic_image': diagnostic_saved
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }
    
    def get_material_count(self, pdf_path: str, page_num: int = 0) -> Dict[str, int]:
        """
        Versión simplificada que solo retorna conteos
        
        Returns:
            {'fusible': 10, 'luminaria': 25, ...}
        """
        result = self.detect_materials(pdf_path, page_num)
        
        if result['success']:
            return result['data']['counts']
        else:
            raise Exception(f"Error en detección: {result.get('error')}")
    
    def batch_detect(self, pdf_paths: list, page_num: int = 0) -> Dict[str, Any]:
        """
        Procesa múltiples PDFs
        
        Args:
            pdf_paths: Lista de rutas a PDFs
            page_num: Página a analizar en cada PDF
            
        Returns:
            Dict con resultados por archivo
        """
        results = {}
        
        for pdf_path in pdf_paths:
            results[pdf_path] = self.detect_materials(pdf_path, page_num)
        
        # Resumen agregado
        total_counts = {}
        successful = 0
        
        for pdf_path, result in results.items():
            if result['success']:
                successful += 1
                for material, count in result['data']['counts'].items():
                    total_counts[material] = total_counts.get(material, 0) + count
        
        return {
            'individual_results': results,
            'summary': {
                'total_pdfs': len(pdf_paths),
                'successful': successful,
                'failed': len(pdf_paths) - successful,
                'aggregated_counts': total_counts
            }
        }


# Ejemplo de uso en servidor MCP
def register_mcp_tool(server):
    """
    Función para registrar la herramienta en un servidor MCP
    
    Args:
        server: Instancia del servidor MCP
    """
    tool = MaterialDetectionTool(templates_dir="./templates")
    
    # Registrar herramienta
    @server.tool()
    async def detect_electrical_components(
        pdf_path: str,
        page_num: int = 0,
        save_diagnostic: bool = False
    ) -> str:
        """
        Detecta componentes eléctricos (fusibles, luminarias, etc.) en planos PDF
        
        Args:
            pdf_path: Ruta al archivo PDF del plano
            page_num: Número de página a analizar (default: 0)
            save_diagnostic: Guardar imagen con detecciones marcadas
            
        Returns:
            JSON con conteos y coordenadas de componentes detectados
        """
        result = tool.detect_materials(pdf_path, page_num, save_diagnostic)
        return json.dumps(result, indent=2, ensure_ascii=False)
    
    @server.tool()
    async def get_component_counts(pdf_path: str, page_num: int = 0) -> str:
        """
        Obtiene solo el conteo de componentes (versión rápida)
        
        Args:
            pdf_path: Ruta al archivo PDF del plano
            page_num: Número de página a analizar
            
        Returns:
            JSON con conteos por tipo de material
        """
        counts = tool.get_material_count(pdf_path, page_num)
        return json.dumps(counts, indent=2, ensure_ascii=False)
    
    return tool


if __name__ == '__main__':
    # Test standalone
    tool = MaterialDetectionTool()
    tool.initialize()
    
    # Ejemplo de detección
    result = tool.detect_materials(
        pdf_path='./topo.pdf',
        page_num=0,
        save_diagnostic=True
    )
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
