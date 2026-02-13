# CotizaBOT - Template Matching Engine

Sistema robusto de detección de componentes eléctricos en planos PDF usando Computer Vision.

## 🎯 Características

- ✅ **Template Matching Multiescala**: Detecta componentes con variaciones de tamaño (0.8x - 1.2x)
- ✅ **Detección Multiorientación**: Componentes rotados (0°, 90°, 180°, 270°)
- ✅ **Non-Maximum Suppression (NMS)**: Elimina detecciones duplicadas usando IoU
- ✅ **Múltiples Variantes**: Soporta plantillas v1, v2, v3 para diferentes formatos de plano
- ✅ **Conversión PDF→Imagen**: Procesamiento de alta calidad (300 DPI)
- ✅ **Salida JSON**: Formato listo para integración con MCP
- ✅ **Visualización Diagnóstica**: Imágenes con bounding boxes etiquetados

## 📦 Instalación

```bash
pip install -r requirements.txt
```

## 🚀 Uso Rápido

### 1. Preparar Plantillas

Organiza tus plantillas PNG en una carpeta con esta convención de nombres:

```
templates/
├── fusible_v1.png          # Fusible formato 1
├── fusible_v2.png          # Fusible formato 2
├── luminaria_v1.png        # Luminaria tipo A
├── luminaria_v2.png        # Luminaria tipo B
└── interruptor_v1.png
```

**Extracción Interactiva** (recomendado para primeras plantillas):

```bash
python template_extractor.py topo.pdf --mode interactive
```

Instrucciones en pantalla:
- Click y arrastra sobre un componente
- Presiona `s` para guardar
- Ingresa nombre del material
- Repite para todos los componentes únicos

### 2. Ejecutar Detección

```bash
python template_matcher.py plano.pdf \
    --templates ./templates \
    --threshold 0.7 \
    --output-json resultados.json \
    --output-image diagnostico.png
```

### 3. Revisar Resultados

**JSON Output** (`resultados.json`):
```json
{
  "pdf_path": "plano.pdf",
  "page": 0,
  "total_detections": 35,
  "counts": {
    "fusible": 12,
    "luminaria": 18,
    "interruptor": 5
  },
  "detections_by_material": {
    "fusible": [
      {
        "x": 245,
        "y": 678,
        "confidence": 0.923,
        "angle": 0,
        "scale": 1.0
      },
      ...
    ]
  }
}
```

**Imagen Diagnóstica**:
- Recuadros de colores por material
- Etiquetas con nivel de confianza
- Visual de todas las detecciones

## 🔧 Integración con MCP

### Opción A: Uso Directo

```python
from mcp_integration import MaterialDetectionTool

# Inicializar
tool = MaterialDetectionTool(templates_dir='./templates')
tool.initialize({'threshold': 0.75, 'nms_iou_threshold': 0.4})

# Detectar
result = tool.detect_materials(
    pdf_path='plano_unifilar.pdf',
    page_num=0,
    save_diagnostic=True
)

print(result['data']['counts'])
# {'fusible': 10, 'luminaria': 25}
```

### Opción B: Integración en Servidor MCP

```python
from mcp_integration import register_mcp_tool
from mcp import Server

server = Server()
detection_tool = register_mcp_tool(server)

# Ahora tienes dos herramientas MCP:
# - detect_electrical_components(pdf_path, page_num, save_diagnostic)
# - get_component_counts(pdf_path, page_num)
```

### Opción C: Despliegue en Render

**Dockerfile** (ejemplo):
```dockerfile
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copiar plantillas
COPY templates/ /app/templates/

CMD ["python", "mcp_server.py"]
```

## 📊 Parámetros de Configuración

### TemplateMatcher

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `templates_dir` | str | `"./templates"` | Carpeta con plantillas PNG |
| `scales` | List[float] | `[0.8, ..., 1.2]` | Escalas a probar (9 valores) |
| `angles` | List[int] | `[0, 90, 180, 270]` | Rotaciones en grados |
| `threshold` | float | `0.7` | Umbral de confianza (0-1) |
| `nms_iou_threshold` | float | `0.4` | Umbral IoU para NMS |
| `dpi` | int | `300` | Resolución PDF→imagen |

### Ajuste Fino

**Aumentar precisión** (más lento):
```python
matcher = TemplateMatcher(
    scales=[0.75, 0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25],
    threshold=0.75,
    dpi=400
)
```

**Optimizar velocidad** (menos preciso):
```python
matcher = TemplateMatcher(
    scales=[0.9, 1.0, 1.1],
    angles=[0, 90, 180],
    threshold=0.65,
    dpi=200
)
```

## 🧪 Testing

Ejecutar suite de validación completa:

```bash
python test_matcher.py
```

Tests incluidos:
- ✅ Cálculo de IoU
- ✅ Non-Maximum Suppression
- ✅ Rotación de plantillas
- ✅ Escalado de plantillas
- ✅ Detección end-to-end
- ✅ Performance benchmarks

## 🎨 Creación de Plantillas - Mejores Prácticas

### 1. Calidad de Plantillas

✅ **Hacer**:
- Extraer componentes en máxima resolución (300 DPI)
- Incluir margen pequeño alrededor del ícono (2-5 px)
- Usar fondo blanco uniforme
- Capturar componente completo y nítido

❌ **Evitar**:
- Plantillas pixeladas o borrosas
- Incluir partes de otros componentes
- Fondo con ruido o texto cercano
- Componentes parcialmente cortados

### 2. Variantes

Para cada material, crea variantes para:
- Diferentes formatos de plano (`fusible_v1.png`, `fusible_v2.png`)
- Estilos distintos del mismo componente
- NO necesitas crear variantes rotadas (se hace automáticamente)

### 3. Tamaño Óptimo

- Mínimo: 20x20 px
- Óptimo: 30-60 px en dimensión mayor
- Máximo: 100x100 px

Plantillas muy grandes ralentizan el procesamiento.

## 🔍 Troubleshooting

### Problema: Muchas detecciones falsas

**Solución**: Aumentar threshold
```python
matcher = TemplateMatcher(threshold=0.8)  # Era 0.7
```

### Problema: No detecta componentes rotados

**Verificación**: Asegurar que angles incluye rotación necesaria
```python
matcher = TemplateMatcher(angles=[0, 45, 90, 135, 180, 225, 270, 315])
```

### Problema: No detecta componentes de distinto tamaño

**Solución**: Ampliar rango de escalas
```python
matcher = TemplateMatcher(scales=[0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4])
```

### Problema: Múltiples detecciones del mismo componente

**Solución**: Ajustar NMS threshold (menor = más estricto)
```python
matcher = TemplateMatcher(nms_iou_threshold=0.3)  # Era 0.4
```

### Problema: Procesamiento muy lento

**Optimizaciones**:
1. Reducir DPI: `dpi=200` en vez de 300
2. Menos escalas: `scales=[0.9, 1.0, 1.1]`
3. Menos ángulos: `angles=[0, 90, 180]`
4. Aumentar threshold: `threshold=0.75`

## 📈 Métricas de Performance

En hardware típico (CPU moderna):

| Configuración | Tiempo/Página | Escalas | Ángulos | DPI |
|---------------|---------------|---------|---------|-----|
| **Rápida** | ~2-5 seg | 3 | 3 | 200 |
| **Balanceada** | ~8-15 seg | 9 | 4 | 300 |
| **Precisión máxima** | ~25-40 seg | 15 | 8 | 400 |

*Estimaciones para plano A3 con 3 tipos de componentes y 2 plantillas cada uno.*

## 🧮 Fundamento Matemático

### IoU (Intersection over Union)

$$IoU(A, B) = \frac{|A \cap B|}{|A \cup B|} = \frac{\text{Área de Intersección}}{\text{Área de Unión}}$$

Usado en NMS para identificar detecciones duplicadas.

### Template Matching

Método: `TM_CCOEFF_NORMED` (Correlation Coefficient Normalized)

$$R(x,y) = \frac{\sum_{x',y'} (T(x',y') \cdot I(x+x', y+y'))}{\sqrt{\sum_{x',y'} T(x',y')^2 \cdot \sum_{x',y'} I(x+x',y+y')^2}}$$

Donde:
- $T$ = Template
- $I$ = Imagen
- $R(x,y)$ = Correlación en posición $(x,y)$

Valores: $-1$ (anti-match) a $+1$ (match perfecto)

## 📁 Estructura del Proyecto

```
cotizabot-template-matching/
├── template_matcher.py       # Motor principal
├── mcp_integration.py         # Wrapper para MCP
├── template_extractor.py      # Herramienta de extracción
├── test_matcher.py            # Suite de tests
├── requirements.txt
├── README.md
├── templates/                 # Tu librería de plantillas
│   ├── fusible_v1.png
│   ├── fusible_v2.png
│   └── ...
└── outputs/                   # Resultados generados
    ├── detections.json
    └── diagnostic.png
```

## 🤝 Contribuciones

Para agregar soporte para nuevos tipos de componentes:

1. Extraer plantillas con `template_extractor.py`
2. Nombrar apropiadamente: `<material>_v<version>.png`
3. Validar con `test_matcher.py`
4. Ajustar threshold si es necesario

## 📝 Licencia

MIT License - Libre para uso en proyectos comerciales y personales.

## 🆘 Soporte

Para issues específicos de CotizaBOT, contacta al equipo de desarrollo.

Para bugs del motor de Template Matching, crear issue con:
- Versión de Python y OpenCV
- Ejemplo de PDF problemático
- Configuración usada
- Output de error completo

---

**Desarrollado con ❤️ para automatizar la cotización de proyectos eléctricos**
