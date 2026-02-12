import fitz
import numpy as np
from sklearn.cluster import DBSCAN
from collections import Counter

# --- ESTA ES LA PARTE QUE DEBES EDITAR CON LOS VALORES QUE SALGAN EN CONSOLA ---
CATALOGO_TECNICO = {
    "TERMICA": {
        "ancho": 10.4, "alto": 8.2, "trazos_ref": 3, "tol": 0.2,
        "clase": "Protección"
    },
    "DISYUNTOR": {
        "ancho": 20.0, "alto": 16.2, "trazos_ref": 3, "tol": 0.4,
        "clase": "Protección"
    },
    "GUARDAMOTOR": {
        "ancho": 45.0, "alto": 75.0, "trazos_ref": 15, "tol": 0.3,
        "clase": "Arranque Motor"
    },
    "CONTACTOR": {
        "ancho": 35.0, "alto": 45.0, "trazos_ref": 12, "tol": 0.3,
        "clase": "Maniobra"
    },
    "FUSIBLE": {
        "ancho": 7.4, "alto": 3.2, "trazos_ref": 2, "tol": 0.1,
        "clase": "Protección"
    },
    "SECCIONADOR": {
        "ancho": 8.4, "alto": 6.8, "trazos_ref": 1, "tol": 0.2,
        "clase": "Seccionamiento"
    },
    "LUMINARIA": {
        "ancho": 6.5, "alto": 6.5, "trazos_ref": 3, "tol": 0.1,
        "clase": "Iluminación"
    },
    "FOTOCELULA": {
        "ancho": 15.0, "alto": 15.0, "trazos_ref": 1, "tol": 0.3,
        "clase": "Control"
    }
}

CATALOGO_PROPORCIONAL = {
    "TERMICA": {
        "ratio": 0.79, 
        "trazos": 3, 
        "tol_ratio": 0.1, 
        "clase": "Protección"
    },
    "DISYUNTOR": {
        "ratio": 0.81, 
        "trazos": 3, 
        "tol_ratio": 0.1, 
        "clase": "Protección"
    },
    "GUARDAMOTOR": {
        "ratio": 1.67, 
        "trazos": 15, 
        "tol_ratio": 0.2, 
        "clase": "Arranque Motor"
    },
    "CONTACTOR": {
        "ratio": 1.29, 
        "trazos": 12, 
        "tol_ratio": 0.15, 
        "clase": "Maniobra"
    },
    "FUSIBLE": {
        "ratio": 0.43, 
        "trazos": 2, 
        "tol_ratio": 0.1, 
        "clase": "Protección"
    },
    "SECCIONADOR": {
        "ratio": 0.81, 
        "trazos": 1, 
        "tol_ratio": 0.1, 
        "clase": "Seccionamiento"
    },
    "LUMINARIA": {
        "ratio": 1.00, 
        "trazos": 3, 
        "tol_ratio": 0.05, 
        "clase": "Iluminación"
    },
    "FOTOCELULA": {
        "ratio": 1.00, 
        "trazos": 1, 
        "tol_ratio": 0.05, 
        "clase": "Control"
    }
}

import fitz

def test_de_vision_vectorial(path_pdf):
    doc = fitz.open(path_pdf)
    page = doc[0]
    
    # Creamos una imagen en blanco del mismo tamaño que la página
    pix = page.get_pixmap()
    # Extraemos todos los dibujos
    drawings = page.get_drawings()
    
    print(f"Se encontraron {len(drawings)} trazos vectoriales.")
    
    # Dibujamos cada trazo en un documento nuevo para ver qué "entiende" la librería
    out_pdf = fitz.open()
    out_page = out_pdf.new_page(width=page.rect.width, height=page.rect.height)
    shape = out_page.new_shape()
    
    for d in drawings:
        shape.draw_rect(d["rect"]) # Dibujamos el recuadro que PyMuPDF detecta
        shape.finish(color=(1, 0, 0), width=0.2)
        
    shape.commit()
    out_pdf.save("verificacion_vectores.pdf")
    print("Revisa 'verificacion_vectores.pdf'. Si los iconos no aparecen marcados, PyMuPDF no los detecta como vectores.")

test_de_vision_vectorial("topo.pdf")