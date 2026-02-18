#!/usr/bin/env python3
"""
Detector de símbolos eléctricos en PDFs unifilares
Versión usando pypdf y pdfplumber (sin PyMuPDF)
Optimizado para detección de fusibles y luminarias
"""

import re
import pdfplumber
from collections import defaultdict
from pathlib import Path
import json
import math

class DetectorSimbolosElectricos:
    def __init__(self, ruta_pdf):
        self.ruta_pdf = ruta_pdf
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
        self.elementos_detectados = defaultdict(list)
        
    def _distancia(self, x1, y1, x2, y2):
        """Distancia euclidiana"""
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    
    def _buscar_texto_cerca(self, x, y, palabras, patron, radio=50):
        """Busca texto que coincida con patrón cerca de un punto"""
        resultados = []
        for palabra in palabras:
            palabra_x = (palabra['x0'] + palabra['x1']) / 2
            palabra_y = (palabra['top'] + palabra['bottom']) / 2
            dist = self._distancia(x, y, palabra_x, palabra_y)
            
            if dist < radio:
                texto = palabra['text']
                if isinstance(patron, str):
                    if patron.lower() in texto.lower():
                        resultados.append((palabra, dist))
                else:  # Es regex
                    if re.search(patron, texto, re.IGNORECASE):
                        resultados.append((palabra, dist))
        
        resultados.sort(key=lambda x: x[1])
        return [r[0] for r in resultados]
    
    def detectar_fusibles(self, palabras, num_pagina):
        """
        Detecta fusibles por el patrón específico:
        - "NAxM" donde N=amperaje, M=cantidad (ej: "2Ax3" = 3 fusibles de 2A)
        - "N A xM" (con espacios)
        - Texto "FUSIBLE" explícito
        """
        count = 0
        fusibles_detectados = set()
        
        print(f"\n   🔍 Buscando fusibles...")
        
        for palabra in palabras:
            texto = palabra['text'].strip()
            palabra_x = (palabra['x0'] + palabra['x1']) / 2
            palabra_y = (palabra['top'] + palabra['bottom']) / 2
            
            # PATRÓN PRINCIPAL: "2Ax3" (sin espacios)
            match_fusible = re.match(r'^(\d+)\s*A\s*x\s*(\d+)$', texto, re.IGNORECASE)
            
            if match_fusible:
                amperaje = match_fusible.group(1)
                cantidad = int(match_fusible.group(2))
                
                pos_key = f"{int(palabra_x)},{int(palabra_y)}"
                if pos_key not in fusibles_detectados:
                    fusibles_detectados.add(pos_key)
                    count += cantidad
                    self.elementos_detectados["fusibles"].append({
                        "texto": texto,
                        "cantidad": cantidad,
                        "amperaje": f"{amperaje}A",
                        "pagina": num_pagina,
                        "posicion": (round(palabra_x, 2), round(palabra_y, 2)),
                        "metodo": "patron_NAxM"
                    })
                    print(f"      ✓ Fusibles: {texto} → {cantidad} unidades de {amperaje}A")
                    continue
            
            # PATRÓN ALTERNATIVO: "xN" separado (buscar amperaje cerca)
            if re.match(r'^x\s*\d+$', texto, re.IGNORECASE):
                match = re.search(r'x\s*(\d+)', texto, re.IGNORECASE)
                cantidad = int(match.group(1))
                
                # Buscar SOLO amperaje simple cerca (ej: "2A", no "2x10A")
                textos_cercanos = self._buscar_texto_cerca(
                    palabra_x, palabra_y, palabras, r'^\d+\s*A$', radio=25
                )
                
                for cercano in textos_cercanos:
                    if re.match(r'^\d+\s*A$', cercano['text'].strip()):
                        pos_key = f"{int(palabra_x)},{int(palabra_y)}"
                        if pos_key not in fusibles_detectados:
                            fusibles_detectados.add(pos_key)
                            count += cantidad
                            
                            match_a = re.search(r'(\d+)\s*A', cercano['text'])
                            amperaje = match_a.group(1) + "A" if match_a else ""
                            
                            self.elementos_detectados["fusibles"].append({
                                "texto": f"{cercano['text']} {texto}",
                                "cantidad": cantidad,
                                "amperaje": amperaje,
                                "pagina": num_pagina,
                                "posicion": (round(palabra_x, 2), round(palabra_y, 2)),
                                "metodo": "xN_separado"
                            })
                            print(f"      ✓ Fusibles: {amperaje} {texto} → {cantidad} unidades")
                            break
            
            # PATRÓN: Texto "FUSIBLE"
            if re.search(r'fusible', texto, re.IGNORECASE):
                textos_x = self._buscar_texto_cerca(
                    palabra_x, palabra_y, palabras, r'x\s*\d+', radio=40
                )
                
                cantidad = 1
                for cercano in textos_x:
                    match = re.search(r'x\s*(\d+)', cercano['text'], re.IGNORECASE)
                    if match:
                        cantidad = int(match.group(1))
                        break
                
                pos_key = f"{int(palabra_x)},{int(palabra_y)}"
                if pos_key not in fusibles_detectados:
                    fusibles_detectados.add(pos_key)
                    count += cantidad
                    self.elementos_detectados["fusibles"].append({
                        "texto": texto,
                        "cantidad": cantidad,
                        "pagina": num_pagina,
                        "posicion": (round(palabra_x, 2), round(palabra_y, 2)),
                        "metodo": "texto_fusible"
                    })
                    print(f"      ✓ Fusibles: {texto} → {cantidad} unidades")
        
        return count
    
    def detectar_luminarias(self, palabras, num_pagina):
        """
        Detecta luminarias por:
        1. Símbolo (R) con multiplicador xN
        2. "xN" en contexto de iluminación (cerca de ILUM, TORRE, etc)
        3. Heurística: Si el documento tiene "ILUMINACIÓN" en el título, 
           contar TODOS los "x3" como luminarias
        """
        count = 0
        luminarias_detectadas = set()
        
        print(f"\n   🔍 Buscando luminarias...")
        
        # Detectar si es un documento de iluminación
        texto_completo = " ".join([p['text'] for p in palabras[:50]])  # Primeras 50 palabras
        es_doc_iluminacion = bool(re.search(r'iluminaci[oó]n\s+(exterior|interior)', texto_completo, re.IGNORECASE))
        
        if es_doc_iluminacion:
            print("      (Documento de iluminación detectado)")
        
        # ESTRATEGIA 1: Buscar (R)
        for palabra in palabras:
            texto = palabra['text'].strip()
            palabra_x = (palabra['x0'] + palabra['x1']) / 2
            palabra_y = (palabra['top'] + palabra['bottom']) / 2
            
            if re.search(r'\(R\)', texto, re.IGNORECASE):
                cantidad = 1
                textos_x = self._buscar_texto_cerca(
                    palabra_x, palabra_y, palabras, r'^x\s*\d+$', radio=60
                )
                
                for cercano in textos_x:
                    match = re.search(r'x\s*(\d+)', cercano['text'], re.IGNORECASE)
                    if match:
                        cantidad = int(match.group(1))
                        break
                
                pos_key = f"{int(palabra_x)},{int(palabra_y)}"
                if pos_key not in luminarias_detectadas:
                    luminarias_detectadas.add(pos_key)
                    count += cantidad
                    self.elementos_detectados["luminaria"].append({
                        "texto": texto,
                        "cantidad": cantidad,
                        "pagina": num_pagina,
                        "posicion": (round(palabra_x, 2), round(palabra_y, 2)),
                        "metodo": "simbolo_R"
                    })
                    print(f"      ✓ Luminarias: (R) → {cantidad} unidad(es)")
        
        # ESTRATEGIA 2: Buscar "xN" en contexto de iluminación
        tokens_x = []
        for palabra in palabras:
            texto = palabra['text'].strip()
            if re.match(r'^x\s*\d+$', texto, re.IGNORECASE):
                palabra_x = (palabra['x0'] + palabra['x1']) / 2
                palabra_y = (palabra['top'] + palabra['bottom']) / 2
                match = re.search(r'x\s*(\d+)', texto, re.IGNORECASE)
                cantidad = int(match.group(1))
                tokens_x.append({
                    'texto': texto,
                    'cantidad': cantidad,
                    'x': palabra_x,
                    'y': palabra_y,
                    'obj': palabra
                })
        
        # Para cada "xN", verificar contexto
        for token in tokens_x:
            # Buscar palabras relacionadas con iluminación cerca
            textos_ilum = self._buscar_texto_cerca(
                token['x'], token['y'], palabras, 
                r'(ilum|luminaria|luz|torre|columna|pabellon|central|emerg|normal)', 
                radio=100  # Radio amplio
            )
            
            # Si es documento de iluminación y NO se encontró contexto cercano,
            # buscar si hay CUALQUIER mención de iluminación en la misma zona vertical
            if es_doc_iluminacion and not textos_ilum:
                # Buscar en la misma franja vertical (±200px en Y)
                textos_ilum = [
                    p for p in palabras
                    if abs((p['top'] + p['bottom'])/2 - token['y']) < 200
                    and re.search(r'(ilum|torre|central)', p['text'], re.IGNORECASE)
                ]
            
            if textos_ilum or es_doc_iluminacion:
                pos_key = f"{int(token['x'])},{int(token['y'])}"
                if pos_key not in luminarias_detectadas:
                    luminarias_detectadas.add(pos_key)
                    count += token['cantidad']
                    
                    contexto = textos_ilum[0]['text'] if textos_ilum else "doc iluminación"
                    
                    self.elementos_detectados["luminaria"].append({
                        "texto": f"{token['texto']} ({contexto})",
                        "cantidad": token['cantidad'],
                        "pagina": num_pagina,
                        "posicion": (round(token['x'], 2), round(token['y'], 2)),
                        "metodo": "xN_contexto_ilum"
                    })
                    print(f"      ✓ Luminarias: {token['texto']} (contexto: {contexto}) → {token['cantidad']} unidades")
        
        return count
    
    def detectar_termicas(self, palabras, num_pagina):
        """Detecta térmicas por patrón TM + número"""
        termicas_ids = set()
        count = 0
        
        for palabra in palabras:
            texto = palabra['text'].strip()
            match = re.search(r'-?TM(\d+)', texto, re.IGNORECASE)
            
            if match:
                id_termica = f"TM{match.group(1)}"
                
                if id_termica not in termicas_ids:
                    termicas_ids.add(id_termica)
                    count += 1
                    
                    palabra_x = (palabra['x0'] + palabra['x1']) / 2
                    palabra_y = (palabra['top'] + palabra['bottom']) / 2
                    
                    self.elementos_detectados["termicas"].append({
                        "id": id_termica,
                        "texto_completo": texto,
                        "pagina": num_pagina,
                        "posicion": (round(palabra_x, 2), round(palabra_y, 2))
                    })
                    print(f"   ✓ Térmica: {texto}")
        
        return count
    
    def detectar_disyuntores(self, palabras, num_pagina):
        """Detecta disyuntores por patrón mA"""
        disyuntores_pos = set()
        count = 0
        
        for palabra in palabras:
            texto = palabra['text'].strip()
            
            if re.search(r'\d+\s*mA', texto, re.IGNORECASE):
                palabra_x = (palabra['x0'] + palabra['x1']) / 2
                palabra_y = (palabra['top'] + palabra['bottom']) / 2
                pos_key = f"{int(palabra_x)},{int(palabra_y)}"
                
                if pos_key not in disyuntores_pos:
                    disyuntores_pos.add(pos_key)
                    count += 1
                    self.elementos_detectados["disyuntores"].append({
                        "texto": texto,
                        "pagina": num_pagina,
                        "posicion": (round(palabra_x, 2), round(palabra_y, 2))
                    })
                    print(f"   ✓ Disyuntor: {texto}")
        
        return count
    
    def detectar_seccionadores(self, palabras, num_pagina):
        """Detecta seccionadores por texto INS"""
        count = 0
        
        for palabra in palabras:
            texto = palabra['text'].strip()
            
            if re.search(r'\bINS\b', texto, re.IGNORECASE):
                count += 1
                palabra_x = (palabra['x0'] + palabra['x1']) / 2
                palabra_y = (palabra['top'] + palabra['bottom']) / 2
                
                self.elementos_detectados["seccionador"].append({
                    "texto": texto,
                    "pagina": num_pagina,
                    "posicion": (round(palabra_x, 2), round(palabra_y, 2))
                })
                print(f"   ✓ Seccionador: {texto}")
        
        return count
    
    def detectar_contactores(self, palabras, num_pagina):
        """Detecta contactores por letra K"""
        contactores_pos = set()
        count = 0
        
        for palabra in palabras:
            texto = palabra['text'].strip()
            
            if re.match(r'^-?K\d*$', texto, re.IGNORECASE):
                palabra_x = (palabra['x0'] + palabra['x1']) / 2
                palabra_y = (palabra['top'] + palabra['bottom']) / 2
                pos_key = f"{int(palabra_x)},{int(palabra_y)}"
                
                if pos_key not in contactores_pos:
                    contactores_pos.add(pos_key)
                    count += 1
                    self.elementos_detectados["contactor"].append({
                        "texto": texto,
                        "tipo": "K",
                        "pagina": num_pagina,
                        "posicion": (round(palabra_x, 2), round(palabra_y, 2))
                    })
                    print(f"   ✓ Contactor: {texto}")
        
        return count
    
    def detectar_fotocelulas(self, palabras, num_pagina):
        """Detecta fotocélulas"""
        count = 0
        
        for palabra in palabras:
            texto = palabra['text'].strip()
            
            if re.search(r'fotoc[eé]lula', texto, re.IGNORECASE):
                count += 1
                palabra_x = (palabra['x0'] + palabra['x1']) / 2
                palabra_y = (palabra['top'] + palabra['bottom']) / 2
                
                self.elementos_detectados["fotocelula"].append({
                    "texto": texto,
                    "tipo": "texto_completo",
                    "pagina": num_pagina,
                    "posicion": (round(palabra_x, 2), round(palabra_y, 2))
                })
                print(f"   ✓ Fotocélula: {texto}")
        
        return count
    
    def detectar_guardamotores(self, palabras, num_pagina):
        """Detecta guardamotores por texto"""
        count = 0
        
        for palabra in palabras:
            texto = palabra['text'].strip()
            
            if re.search(r'guardamotor', texto, re.IGNORECASE):
                count += 1
                palabra_x = (palabra['x0'] + palabra['x1']) / 2
                palabra_y = (palabra['top'] + palabra['bottom']) / 2
                
                self.elementos_detectados["guardamotor"].append({
                    "texto": texto,
                    "pagina": num_pagina,
                    "posicion": (round(palabra_x, 2), round(palabra_y, 2))
                })
                print(f"   ✓ Guardamotor: {texto}")
        
        return count
    
    def analizar(self):
        """Análisis completo del PDF"""
        try:
            with pdfplumber.open(self.ruta_pdf) as pdf:
                print(f"📄 PDF: {self.ruta_pdf}")
                print(f"   Páginas: {len(pdf.pages)}\n")
                
                for num_pagina, pagina in enumerate(pdf.pages, 1):
                    print(f"\n{'='*70}")
                    print(f"📄 PÁGINA {num_pagina}")
                    print(f"{'='*70}")
                    
                    # Extraer palabras con posiciones
                    palabras = pagina.extract_words(
                        x_tolerance=3,
                        y_tolerance=3,
                        keep_blank_chars=False
                    )
                    
                    print(f"   📝 Palabras extraídas: {len(palabras)}")
                    
                    # Detectar cada tipo de símbolo
                    self.resultados["termicas"] += self.detectar_termicas(palabras, num_pagina)
                    self.resultados["disyuntores"] += self.detectar_disyuntores(palabras, num_pagina)
                    self.resultados["seccionador"] += self.detectar_seccionadores(palabras, num_pagina)
                    self.resultados["contactor"] += self.detectar_contactores(palabras, num_pagina)
                    self.resultados["fotocelula"] += self.detectar_fotocelulas(palabras, num_pagina)
                    self.resultados["guardamotor"] += self.detectar_guardamotores(palabras, num_pagina)
                    
                    # CRÍTICO: Fusibles y Luminarias
                    self.resultados["fusibles"] += self.detectar_fusibles(palabras, num_pagina)
                    self.resultados["luminaria"] += self.detectar_luminarias(palabras, num_pagina)
            
            return self.resultados
            
        except Exception as e:
            print(f"\n❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def mostrar_resultados(self):
        """Muestra resumen"""
        print("\n" + "="*70)
        print("📊 RESULTADOS FINALES - CONTEO DE MATERIALES")
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
            print(f"{icono} {nombre:.<50} {cantidad:>3}")
        
        print("="*70)
        print(f"{'TOTAL':.<54} {total:>3}")
        print("="*70)
    
    def exportar_json(self, archivo="resultados_conteo.json"):
        """Exporta a JSON"""
        datos = {
            "pdf": self.ruta_pdf,
            "resumen": self.resultados,
            "total_elementos": sum(self.resultados.values()),
            "detalle": {k: v for k, v in self.elementos_detectados.items()}
        }
        
        with open(archivo, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Resultados: {archivo}")
        return datos


def main():
    import sys
    
    print("=" * 70)
    print("🔍 DETECTOR DE SÍMBOLOS ELÉCTRICOS - UNIFILARES")
    print("=" * 70 + "\n")
    
    if len(sys.argv) < 2:
        print("❌ Uso: python detector.py <ruta_pdf>")
        return
    
    ruta_pdf = sys.argv[1]
    
    if not Path(ruta_pdf).exists():
        print(f"❌ No existe: {ruta_pdf}")
        return
    
    detector = DetectorSimbolosElectricos(ruta_pdf)
    resultados = detector.analizar()
    
    if resultados:
        detector.mostrar_resultados()
        detector.exportar_json()
        
        print("\n✅ Completado")
        print(f"\n{json.dumps(resultados, indent=2, ensure_ascii=False)}")
    else:
        print("\n❌ Error")


if __name__ == "__main__":
    main()