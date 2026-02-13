#!/bin/bash
# Script de instalación rápida - CotizaBOT Template Matching

echo "🚀 CotizaBOT Template Matching - Instalación Rápida"
echo "=================================================="

# Verificar Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 no encontrado. Por favor instala Python 3.8+"
    exit 1
fi

echo "✅ Python encontrado: $(python3 --version)"

# Crear entorno virtual
echo ""
echo "📦 Creando entorno virtual..."
python3 -m venv venv

# Activar entorno
echo "🔌 Activando entorno..."
source venv/bin/activate

# Instalar dependencias
echo "📥 Instalando dependencias..."
pip install --upgrade pip
pip install -r requirements.txt

# Crear estructura de directorios
echo "📁 Creando directorios..."
mkdir -p templates
mkdir -p outputs

echo ""
echo "✅ Instalación completada!"
echo ""
echo "📝 Próximos pasos:"
echo "1. Activar entorno: source venv/bin/activate"
echo "2. Agregar plantillas a la carpeta 'templates/'"
echo "3. Ejecutar: python template_matcher.py --help"
echo ""
echo "📚 Ver README.md para más información"
