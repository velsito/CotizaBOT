# 🚀 Referencia Rápida - CotizaBOT Template Matching

## Instalación

```bash
# 1. Clonar/descargar el proyecto
cd cotizabot_template_matching

# 2. Instalación rápida (Linux/Mac)
chmod +x quick_start.sh
./quick_start.sh

# O instalación manual
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Comandos Esenciales

### 1️⃣ Extraer Plantillas (Primera vez)

```bash
# Modo interactivo - Selecciona componentes con el mouse
python template_extractor.py mi_plano.pdf

# Click + arrastra sobre componente → presiona 's' → ingresa nombre → repite
```

### 2️⃣ Detectar Componentes

```bash
# Detección básica
python template_matcher.py mi_plano.pdf

# Con opciones personalizadas
python template_matcher.py mi_plano.pdf \
    --templates ./templates \
    --threshold 0.75 \
    --output-json resultados.json \
    --output-image diagnostico.png
```

### 3️⃣ Uso Programático (Python)

```python
from template_matcher import TemplateMatcher

# Inicializar
matcher = TemplateMatcher(
    templates_dir='./templates',
    threshold=0.7
)

# Detectar
results, image, detections = matcher.detect('plano.pdf')

# Ver resultados
print(results['counts'])
# {'fusible': 12, 'luminaria': 25, ...}

# Guardar visualización
matcher.visualize_detections(image, detections, 'output.png')
```

### 4️⃣ Integración MCP

```python
from mcp_integration import MaterialDetectionTool

tool = MaterialDetectionTool('./templates')
result = tool.detect_materials('plano.pdf', save_diagnostic=True)

print(result['data']['counts'])
```

## Parámetros Importantes

| Parámetro | Valor Default | Cuándo Cambiar |
|-----------|---------------|----------------|
| `threshold` | 0.7 | ↑ 0.8 si hay muchas falsas detecciones<br>↓ 0.6 si no detecta componentes |
| `nms_iou_threshold` | 0.4 | ↓ 0.3 si detecta el mismo componente varias veces |
| `dpi` | 300 | ↑ 400 para mayor precisión<br>↓ 200 para mayor velocidad |
| `scales` | [0.8...1.2] | Ampliar rango si componentes varían mucho de tamaño |

## Troubleshooting Rápido

### ❌ "No detecta componentes"
```python
# Solución: Bajar threshold
matcher = TemplateMatcher(threshold=0.6)
```

### ❌ "Detecta el mismo componente múltiples veces"
```python
# Solución: NMS más estricto
matcher = TemplateMatcher(nms_iou_threshold=0.3)
```

### ❌ "Muchas falsas detecciones"
```python
# Solución: Threshold más alto
matcher = TemplateMatcher(threshold=0.8)
```

### ❌ "No detecta componentes rotados"
```python
# Solución: Agregar más ángulos
matcher = TemplateMatcher(angles=[0, 45, 90, 135, 180, 225, 270, 315])
```

### ❌ "Muy lento"
```python
# Solución: Configuración rápida
matcher = TemplateMatcher(
    scales=[0.9, 1.0, 1.1],
    angles=[0, 90, 180],
    dpi=200
)
```

## Estructura de Carpetas

```
cotizabot_template_matching/
├── template_matcher.py       ← Motor principal
├── mcp_integration.py         ← Wrapper para MCP
├── template_extractor.py      ← Extraer plantillas
├── templates/                 ← Tus plantillas PNG
│   ├── fusible_v1.png
│   └── luminaria_v1.png
└── outputs/                   ← Resultados
    ├── detections.json
    └── diagnostic.png
```

## Formatos de Salida

### JSON
```json
{
  "total_detections": 35,
  "counts": {
    "fusible": 12,
    "luminaria": 18
  },
  "detections_by_material": {
    "fusible": [
      {"x": 245, "y": 678, "confidence": 0.92}
    ]
  }
}
```

### CSV (Opcional)
```
Material,X,Y,Confidence
fusible,245,678,0.92
luminaria,340,120,0.88
```

## Testing

```bash
# Ejecutar tests
python test_matcher.py

# Ver ejemplos de uso
python ejemplos_uso.py
```

## Recursos

- 📖 **Documentación completa**: `README.md`
- 🔧 **Optimización avanzada**: `optimizacion_avanzada.py`
- 💡 **Ejemplos**: `ejemplos_uso.py`
- 🧪 **Tests**: `test_matcher.py`

## Ayuda

```bash
# Ayuda de cada script
python template_matcher.py --help
python template_extractor.py --help
```

---

**Tip**: Comienza con la configuración por defecto y ajusta solo si es necesario. El sistema está optimizado para casos comunes.
