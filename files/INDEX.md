# 📦 CotizaBOT - Template Matching System

Sistema completo de detección de componentes eléctricos en planos PDF usando Computer Vision con OpenCV.

---

## 🚀 Inicio Rápido

1. **Lee primero**: [`QUICK_REFERENCE.md`](QUICK_REFERENCE.md) ← Comandos esenciales
2. **Instala**: Ejecuta `./quick_start.sh` o sigue instrucciones en README
3. **Extrae plantillas**: `python template_extractor.py tu_plano.pdf`
4. **Detecta**: `python template_matcher.py tu_plano.pdf`

---

## 📚 Documentación

### Para Comenzar
- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Guía de referencia rápida (EMPIEZA AQUÍ)
- **[README.md](README.md)** - Documentación completa del sistema
- **[quick_start.sh](quick_start.sh)** - Script de instalación automática

### Configuración
- **[config.json](config.json)** - Archivo de configuración con ejemplos
- **[requirements.txt](requirements.txt)** - Dependencias Python

---

## 🛠️ Archivos del Sistema

### Core (Motor Principal)
- **[template_matcher.py](template_matcher.py)** - Motor de detección con template matching multiescala
  - Clase `TemplateMatcher`: Detector principal
  - Clase `Detection`: Estructura de datos para detecciones
  - Implementa NMS (Non-Maximum Suppression)
  - Conversión PDF → Imagen
  - Visualización de diagnósticos

### Integración
- **[mcp_integration.py](mcp_integration.py)** - Wrapper para servidor MCP
  - Clase `MaterialDetectionTool`: Herramienta lista para MCP
  - Métodos: `detect_materials()`, `get_material_count()`, `batch_detect()`
  - Función `register_mcp_tool()` para registro en servidor

### Utilidades
- **[template_extractor.py](template_extractor.py)** - Herramienta para crear plantillas
  - Modo interactivo (click & drag)
  - Extracción por lotes
  - Generación de variantes rotadas

### Testing y Ejemplos
- **[test_matcher.py](test_matcher.py)** - Suite completa de tests unitarios
  - Tests de IoU
  - Tests de NMS
  - Tests de rotación y escalado
  - Tests de integración end-to-end
  - Benchmarks de rendimiento

- **[ejemplos_uso.py](ejemplos_uso.py)** - 7 ejemplos prácticos completos
  1. Uso básico
  2. Múltiples formatos de plano
  3. Ajuste fino de parámetros
  4. Integración con MCP
  5. Manejo de errores
  6. Filtrado por confianza
  7. Exportación para CAD

- **[optimizacion_avanzada.py](optimizacion_avanzada.py)** - Técnicas avanzadas
  - Preprocesamiento de plantillas
  - Edge matching
  - Búsqueda piramidal
  - Paralelización
  - Feature matching (SIFT/ORB)
  - Clustering espacial
  - Validación de coherencia

---

## 📁 Estructura del Proyecto

```
cotizabot_template_matching/
│
├── 📄 INICIO RÁPIDO
│   ├── QUICK_REFERENCE.md          ← LEE ESTO PRIMERO
│   ├── README.md                    ← Documentación completa
│   └── quick_start.sh               ← Instalación automática
│
├── ⚙️ CONFIGURACIÓN
│   ├── config.json                  ← Parámetros del sistema
│   └── requirements.txt             ← Dependencias
│
├── 🔧 SISTEMA CORE
│   ├── template_matcher.py          ← Motor principal ⭐
│   ├── mcp_integration.py           ← Wrapper MCP
│   └── template_extractor.py        ← Crear plantillas
│
├── 🧪 TESTING & EJEMPLOS
│   ├── test_matcher.py              ← Tests unitarios
│   ├── ejemplos_uso.py              ← Casos de uso
│   └── optimizacion_avanzada.py     ← Técnicas avanzadas
│
└── 📂 DATOS
    └── templates/                   ← Tus plantillas PNG
        └── README.md                 ← Guía de plantillas
```

---

## 🎯 Casos de Uso Principales

### 1. Detección Simple
```bash
python template_matcher.py mi_plano.pdf
```

### 2. Uso Programático
```python
from template_matcher import TemplateMatcher

matcher = TemplateMatcher('./templates')
results, _, _ = matcher.detect('plano.pdf')
print(results['counts'])
```

### 3. Integración MCP
```python
from mcp_integration import register_mcp_tool
tool = register_mcp_tool(server)
```

### 4. Procesamiento Batch
```python
from mcp_integration import MaterialDetectionTool

tool = MaterialDetectionTool('./templates')
results = tool.batch_detect(['p1.pdf', 'p2.pdf'])
```

---

## 🔍 Características Clave

✅ **Multiescala**: Detecta componentes de 0.8x a 1.2x del tamaño de la plantilla  
✅ **Multiorientación**: Rotaciones automáticas (0°, 90°, 180°, 270°)  
✅ **NMS Inteligente**: Elimina duplicados usando IoU  
✅ **Alta Calidad**: Conversión PDF a 300 DPI  
✅ **Múltiples Formatos**: Soporta variantes v1, v2, v3 de plantillas  
✅ **Visualización**: Imágenes diagnósticas con bounding boxes  
✅ **JSON/CSV**: Exportación en múltiples formatos  
✅ **MCP Ready**: Integración directa con servidores MCP  

---

## 📊 Rendimiento

| Configuración | Tiempo/Página | Precisión |
|---------------|---------------|-----------|
| Rápida | ~2-5 seg | Media |
| Balanceada (Default) | ~8-15 seg | Alta |
| Máxima Precisión | ~25-40 seg | Muy Alta |

*Para plano A3 con 3 tipos de componentes*

---

## 🆘 Obtener Ayuda

### Documentación
1. **Inicio**: [`QUICK_REFERENCE.md`](QUICK_REFERENCE.md)
2. **Completa**: [`README.md`](README.md)
3. **Avanzada**: [`optimizacion_avanzada.py`](optimizacion_avanzada.py)

### Ejemplos Prácticos
```bash
python ejemplos_uso.py  # Menu interactivo
```

### Tests
```bash
python test_matcher.py  # Suite completa de validación
```

### CLI Help
```bash
python template_matcher.py --help
python template_extractor.py --help
```

---

## 🔧 Solución de Problemas Común

| Problema | Archivo | Sección |
|----------|---------|---------|
| No detecta componentes | QUICK_REFERENCE.md | Troubleshooting |
| Detecciones duplicadas | QUICK_REFERENCE.md | Troubleshooting |
| Optimizar velocidad | optimizacion_avanzada.py | Optimización de Rendimiento |
| Mejorar precisión | optimizacion_avanzada.py | Optimización de Plantillas |
| Integrar con MCP | mcp_integration.py | Documentación inline |

---

## 🚢 Despliegue en Render

Ver sección de despliegue en [`README.md`](README.md#opción-c-despliegue-en-render)

---

## 📝 Licencia

MIT License - Uso libre en proyectos comerciales y personales.

---

## 🎓 Flujo de Trabajo Recomendado

### Primera Vez
1. Lee [`QUICK_REFERENCE.md`](QUICK_REFERENCE.md)
2. Ejecuta `./quick_start.sh`
3. Extrae plantillas: `python template_extractor.py topo.pdf`
4. Prueba detección: `python template_matcher.py topo.pdf`
5. Revisa `diagnostic.png` y `detections.json`

### Desarrollo
1. Ajusta parámetros en [`config.json`](config.json) según necesites
2. Ejecuta [`ejemplos_uso.py`](ejemplos_uso.py) para casos específicos
3. Consulta [`optimizacion_avanzada.py`](optimizacion_avanzada.py) para técnicas avanzadas

### Producción
1. Integra usando [`mcp_integration.py`](mcp_integration.py)
2. Ejecuta [`test_matcher.py`](test_matcher.py) para validar
3. Despliega en Render siguiendo [`README.md`](README.md)

---

**Desarrollado para CotizaBOT** | Template Matching con OpenCV & PyMuPDF
