import fitz  # PyMuPDF
import os

def convertir_tableros_a_png(carpeta_entrada="tableros\\Unifilares", carpeta_salida="imagenes_tableros"):
    # Crear carpeta de salida si no existe
    if not os.path.exists(carpeta_salida):
        os.makedirs(carpeta_salida)
        print(f"Carpeta '{carpeta_salida}' creada.")

    # Listar archivos PDF en la carpeta
    archivos_pdf = [f for f in os.listdir(carpeta_entrada) if f.lower().endswith('.pdf')]

    if not archivos_pdf:
        print(f"No se encontraron archivos PDF en '{carpeta_entrada}'.")
        return

    for archivo in archivos_pdf:
        ruta_pdf = os.path.join(carpeta_entrada, archivo)
        nombre_base = os.path.splitext(archivo)[0]
        
        # Abrir el PDF
        documento = fitz.open(ruta_pdf)
        print(f"Procesando: {archivo} ({len(documento)} páginas)")

        for num_pagina in range(len(documento)):
            pagina = documento.load_page(num_pagina)
            
            # Definir resolución (300 DPI es ideal para planos técnicos)
            # Un zoom de 4x (300/72) suele ser el estándar
            zoom = 300 / 72 
            matriz = fitz.Matrix(zoom, zoom)
            
            # Generar la imagen (pixmap)
            pix = pagina.get_pixmap(matrix=matriz)
            
            # Guardar el archivo
            nombre_imagen = f"{nombre_base}_pag_{num_pagina + 1}.png"
            ruta_imagen = os.path.join(carpeta_salida, nombre_imagen)
            pix.save(ruta_imagen)
            print(f"  -> Guardado: {nombre_imagen}")

        documento.close()
    print("\n✅ Conversión finalizada con éxito.")

if __name__ == "__main__":
    convertir_tableros_a_png()