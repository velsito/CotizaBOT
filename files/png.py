import cv2
import numpy as np
import os

def generar_tiles_entrenamiento(carpeta_origen="convertidos", 
                                carpeta_destino="pedazos", 
                                tile_size=1280, 
                                overlap=200, 
                                umbral_detalle=0.005):
    """
    Divide los planos en fragmentos de 1280x1280 filtrando los que están vacíos.
    """
    if not os.path.exists(carpeta_destino):
        os.makedirs(carpeta_destino)
        print(f"📁 Carpeta creada: {carpeta_destino}")

    # Listar archivos PNG exportados a 300 DPI
    imagenes = [f for f in os.listdir(carpeta_origen) if f.lower().endswith('.png')]
    
    if not imagenes:
        print(f"⚠️ No hay imágenes en {carpeta_origen}. Ejecuta primero el script de exportación.")
        return

    total_tiles_generados = 0

    for img_name in imagenes:
        ruta_img = os.path.join(carpeta_origen, img_name)
        img = cv2.imread(ruta_img)
        if img is None: continue
        
        # Convertir a gris para analizar contenido rápidamente
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        
        nombre_base = os.path.splitext(img_name)[0]
        count = 0

        # Barrido por coordenadas con solapamiento (overlap)
        for y in range(0, h - tile_size // 2, tile_size - overlap):
            for x in range(0, w - tile_size // 2, tile_size - overlap):
                
                # Ajustar el cuadro para no salir de los bordes del plano
                y_end = min(y + tile_size, h)
                x_end = min(x + tile_size, w)
                y_start = max(0, y_end - tile_size)
                x_start = max(0, x_end - tile_size)

                # Extraer el fragmento (Tile)
                tile = img[y_start:y_end, x_start:x_end]
                tile_gray = gray[y_start:y_end, x_start:x_end]

                # --- FILTRO DE CONTENIDO ---
                # Contamos píxeles que no son blancos (trazos del plano)
                # Un valor < 250 indica que hay dibujo o texto
                puntos_interes = np.sum(tile_gray < 250)
                proporcion = puntos_interes / tile_gray.size

                if proporcion > umbral_detalle:
                    nombre_tile = f"{nombre_base}_tile_{count}.jpg"
                    ruta_salida = os.path.join(carpeta_destino, nombre_tile)
                    
                    # Guardar como JPG para que Roboflow lo procese más rápido
                    cv2.imwrite(ruta_salida, tile, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                    count += 1
                    total_tiles_generados += 1
        
        print(f"✅ {img_name}: Generados {count} fragmentos con contenido.")

    print(f"\n🚀 Proceso finalizado. Total de imágenes para Roboflow: {total_tiles_generados}")

if __name__ == "__main__":
    # Asegúrate de que la carpeta de origen coincida con la de tu script anterior
    generar_tiles_entrenamiento()