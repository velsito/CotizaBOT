"""
Sistema de Dimensionamiento de Tableros Eléctricos
Usando Pandas para manipulación de Excel sin necesidad de tener Excel abierto.
- agregar memoria para interacción con el bot y poder enviarle los datos de la consulta mediante mensajes de repregunta, evitando pasar el listado manualmente, de forma que se agilice el proceso de carga de datos
- seccionador, disyuntor, interrruptor, térmica, 
"""
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path

# --- CONFIGURACIÓN ---
FILE_NAME = 'data\\tableros.xlsm'

from core_models import cargar_datos, MaterialInput, ConfiguracionInput, CalculoRielesInput

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TipoTablero(Enum):
    """Tipos de tablero soportados"""
    ESTANCO = "ESTANCO"
    MODULAR = "MODULAR"


class TipoCategoria(Enum):
    """Categorías de materiales"""
    SELECCIONADOR = "SELECCIONADOR"
    GABINETE = "GABINETE"
    ACCESORIO = "ACCESORIO"
    TERMICA = "TERMICA"
    DIFERENCIAL = "DIFERENCIAL"


@dataclass
class Material:
    """Representa un material en el listado"""
    codigo: str
    descripcion: str
    cantidad: int
    categoria: str
    ancho_mm: float = 0.0


@dataclass
class Gabinete:
    """Representa un gabinete con sus propiedades"""
    codigo: str
    descripcion: str
    tipo: str
    ancho: float
    alto: float
    profundidad: float
    largo_riel: float
    cantidad_columnas: int


@dataclass
class ConfiguracionTablero:
    """Configuración leída desde Excel"""
    seleccionador_ref: str
    tiene_borneras: bool
    aplicar_reserva: bool
    tipo_contrafrente: str
    porcentaje_reserva: float = 0.15

logger = logging.getLogger(__name__)

class ExcelDataLoader:
    """Maneja la carga de datos desde Excel usando Pandas (sin necesidad de Excel abierto)"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path

    def cargar_todas_bases(self) -> Dict[str, pd.DataFrame]:
        """Carga todas las hojas del archivo .xlsm a memoria"""
        hojas_mapping = {
            'seleccionadores': 'SELECCIONADORES',
            'envolventes': 'ENVOLVENTES',
            'termicas': 'TERMICAS',
            'diferencial': 'DIFERENCIAL',
            'modular': 'MODULAR',
            'estanco': 'ESTANCO',
            'bd_maestra': 'Base de datos'
        }
        
        datos = {}
        try:
            # Leemos el archivo completo una sola vez para ser más eficientes
            # engine='openpyxl' es vital para archivos .xlsm en Linux/Docker
            excel_file = pd.ExcelFile(self.file_path, engine='openpyxl')
            
            for key, nombre_hoja in hojas_mapping.items():
                if nombre_hoja in excel_file.sheet_names:
                    df = excel_file.parse(nombre_hoja)
                    # Limpieza de nombres de columnas (quitar espacios)
                    df.columns = [str(c).strip() for c in df.columns]
                    datos[key] = df
                    logger.info(f"Cargada hoja '{nombre_hoja}': {len(df)} registros")
                else:
                    logger.warning(f"La hoja '{nombre_hoja}' no existe en el archivo.")
            
            return datos

        except Exception as e:
            logger.error(f"Error crítico cargando la base de datos Excel: {e}")
            raise


class CalculadorRieles:
    """Calcula la distribución de dispositivos en rieles"""
    
    def __init__(self, config: ConfiguracionTablero):
        self.config = config
    
    def calcular_rieles_necesarios(
        self, 
        largo_riel: float,
        ancho_sel: float,
        anchos_dif: List[float],
        anchos_term: List[float]
    ) -> int:
        """
        Calcula el número total de rieles necesarios.
        Retorna 999 si no es posible la configuración.
        """
        if largo_riel < ancho_sel:
            return 999
        
        # Rieles para diferenciales
        rieles_dif = self._calcular_rieles_categoria(largo_riel, anchos_dif)
        if rieles_dif == 999:
            return 999
        
        # Rieles para térmicas
        rieles_term = self._calcular_rieles_categoria(largo_riel, anchos_term)
        if rieles_term == 999:
            return 999
        
        # Total de protecciones
        rieles_prot = rieles_dif + rieles_term
        
        # Si diferenciales > 1 fila, agregar riel extra
        if rieles_dif > 1:
            rieles_prot += 1
        
        # Aplicar reserva si está configurada
        if self.config.aplicar_reserva:
            rieles_prot = self._aplicar_reserva(
                rieles_prot, 
                largo_riel, 
                anchos_dif, 
                anchos_term
            )
        
        # Total: Seleccionador + Protecciones + Borneras (opcional)
        total = 1 + rieles_prot + (1 if self.config.tiene_borneras else 0)
        
        logger.debug(
            f"Rieles calculados - Dif:{rieles_dif}, Term:{rieles_term}, "
            f"Total:{total} (largo_riel:{largo_riel}mm)"
        )
        
        return total
    
    @staticmethod
    def _calcular_rieles_categoria(
        largo_riel: float, 
        anchos: List[float]
    ) -> int:
        """Calcula rieles para una categoría específica"""
        if not anchos:
            return 0
        
        rieles = 1
        espacio_usado = 0.0
        
        for ancho in anchos:
            if ancho > largo_riel:
                return 999  # Dispositivo no cabe
            
            if espacio_usado + ancho > largo_riel:
                rieles += 1
                espacio_usado = ancho
            else:
                espacio_usado += ancho
        
        return rieles
    
    def _aplicar_reserva(
        self,
        rieles_actuales: int,
        largo_riel: float,
        anchos_dif: List[float],
        anchos_term: List[float]
    ) -> int:
        """Aplica la regla de reserva del 20%"""
        capacidad_total = rieles_actuales * largo_riel
        ocupacion_total = sum(anchos_dif) + sum(anchos_term)
        
        if capacidad_total > 0:
            espacio_libre = capacidad_total - ocupacion_total
            porcentaje_libre = espacio_libre / capacidad_total
            
            if porcentaje_libre < self.config.porcentaje_reserva:
                logger.info(
                    f"Aplicando reserva: {porcentaje_libre:.1%} < "
                    f"{self.config.porcentaje_reserva:.1%}"
                )
                return rieles_actuales + 1
        
        return rieles_actuales


class SelectorGabinete:
    """Selecciona el gabinete óptimo según criterios jerárquicos"""
    
    def __init__(self, df_envolventes: pd.DataFrame):
        self.df_env = df_envolventes
    
    def seleccionar_gabinete(
        self,
        tipo_tablero: TipoTablero,
        calculador: CalculadorRieles,
        ancho_sel: float,
        anchos_dif: List[float],
        anchos_term: List[float]
    ) -> Optional[Gabinete]:
        """Selecciona el gabinete óptimo"""
        
        if tipo_tablero == TipoTablero.ESTANCO:
            return self._seleccionar_estanco(
                calculador, ancho_sel, anchos_dif, anchos_term
            )
        elif tipo_tablero == TipoTablero.MODULAR:
            return self._seleccionar_modular(
                calculador, ancho_sel, anchos_dif, anchos_term
            )
        
        return None
    
    def _seleccionar_estanco(
        self, 
        calculador: CalculadorRieles,
        ancho_sel: float,
        anchos_dif: List[float],
        anchos_term: List[float]
    ) -> Optional[Gabinete]:
        """Selecciona gabinete estanco según jerarquía"""
        
        df_est = self.df_env[
            (self.df_env['TIPO'] == 'ESTANCO') & 
            (self.df_env['PROFUNDIDAD'] == 225)
        ]
        
        # jerarquia de búsqueda
        criterios = [
            (450, 0, 750),      # 450mm, alto ≤750
            (600, 1050, 1050),  # 600mm, alto =1050
            (750, 1050, 1200),  # 750mm, alto 1050-1200
            (900, 1200, 9999)   # 900mm, alto >1200
        ]
        
        for ancho, alto_min, alto_max in criterios:
            candidatos = df_est[
                (df_est['ANCHO'] == ancho) &
                (df_est['ALTO'] >= alto_min) &
                (df_est['ALTO'] <= alto_max)
            ].sort_values('ALTO')
            
            ganador = self._evaluar_candidatos(
                candidatos, calculador, ancho_sel, anchos_dif, anchos_term
            )
            
            if ganador:
                return ganador
        
        return None
    
    def _seleccionar_modular(
        self,
        calculador: CalculadorRieles,
        ancho_sel: float,
        anchos_dif: List[float],
        anchos_term: List[float]
    ) -> Optional[Gabinete]:
        """Selecciona gabinete modular según jerarquía"""
        
        df_mod = self.df_env[
            (self.df_env['TIPO'] == 'MODULAR') &
            (self.df_env['PROFUNDIDAD'] == 300)
        ]
        
        # Primero: 450mm, alto ≤1800
        candidatos_450 = df_mod[
            (df_mod['ANCHO'] == 450) &
            (df_mod['ALTO'] <= 1800)
        ].sort_values('ALTO')
        
        ganador = self._evaluar_candidatos(
            candidatos_450, calculador, ancho_sel, anchos_dif, anchos_term
        )
        
        if ganador:
            return ganador
        
        # Segundo: Mayores dimensiones
        candidatos_sup = df_mod[
            (df_mod['ALTO'] > 1800) |
            (df_mod['ANCHO'] > 450)
        ].sort_values(['ALTO', 'ANCHO'])
        
        return self._evaluar_candidatos(
            candidatos_sup, calculador, ancho_sel, anchos_dif, anchos_term
        )
    
    def _evaluar_candidatos(
        self,
        candidatos: pd.DataFrame,
        calculador: CalculadorRieles,
        ancho_sel: float,
        anchos_dif: List[float],
        anchos_term: List[float]
    ) -> Optional[Gabinete]:
        """Evalúa lista de candidatos y retorna el primero que cumpla"""
        
        for _, row in candidatos.iterrows():
            rieles_necesarios = calculador.calcular_rieles_necesarios(
                row['LARGO_RIEL'], ancho_sel, anchos_dif, anchos_term
            )
            
            if rieles_necesarios <= row['CANTIDAD DE COLUMNAS']:
                logger.info(
                    f"Gabinete seleccionado: {row['DESCRIPCION']} "
                    f"({rieles_necesarios}/{row['CANTIDAD DE COLUMNAS']} rieles)"
                )
                
                return Gabinete(
                    codigo=str(row['CODIGO']),
                    descripcion=str(row['DESCRIPCION']),
                    tipo=str(row['TIPO']),
                    ancho=float(row['ANCHO']),
                    alto=float(row['ALTO']),
                    profundidad=float(row['PROFUNDIDAD']),
                    largo_riel=float(row['LARGO_RIEL']),
                    cantidad_columnas=int(row['CANTIDAD DE COLUMNAS'])
                )
        
        return None


class ProcesadorMateriales:
    """Procesa y busca materiales en las bases de datos"""
    
    def __init__(self, datos: Dict[str, pd.DataFrame]):
        self.datos = datos
        self.dict_descripciones = self._crear_dict_descripciones()
    
    def _crear_dict_descripciones(self) -> Dict[str, str]:
        """Crea diccionario de códigos a descripciones"""
        
        # ✅ Verificar si bd_maestra existe
        if 'bd_maestra' not in self.datos:
            logger.warning("⚠️  bd_maestra no disponible, usando descripciones por defecto")
            return {}
        
        try:
            df_bd = self.datos['bd_maestra']
            
            # Verificar que tenga al menos 2 columnas
            if len(df_bd.columns) < 2:
                logger.error("bd_maestra debe tener al menos 2 columnas")
                return {}
            
            # Crear diccionario código -> descripción
            return pd.Series(
                df_bd.iloc[:, 1].values,  # Segunda columna = descripciones
                index=df_bd.iloc[:, 0].astype(str).str.strip()  # Primera = códigos
            ).to_dict()
            
        except Exception as e:
            logger.error(f"Error creando diccionario de descripciones: {e}")
            return {}
    
    def procesar_seleccionador(
        self, 
        referencia: str
    ) -> Tuple[Optional[Material], Optional[str], Optional[float]]:
        """
        Procesa el seleccionador.
        Retorna: (Material, tipo_tablero, ancho_mm)
        """
        df_sel = self.datos['seleccionadores']
        match = df_sel[
            df_sel['REFE'].astype(str).str.strip() == referencia
        ]
        
        if match.empty:
            logger.error(f"Seleccionador '{referencia}' no encontrado")
            return None, None, None
        
        row = match.iloc[0]
        material = Material(
            codigo=str(row['CODIGO']),
            descripcion=str(row['DESCRIPCION']),
            cantidad=1,
            categoria=TipoCategoria.SELECCIONADOR.value,
            ancho_mm=float(row['MEDIDAS'])
        )
        
        return material, str(row['TABLERO']), float(row['MEDIDAS'])
    
    def procesar_protecciones(
        self, 
        df_materiales: pd.DataFrame
    ) -> Tuple[List[Material], List[float], List[float]]:
        """
        Procesa térmicas y diferenciales.
        Retorna: (lista_materiales, anchos_dif, anchos_term)
        """
        materiales = []
        anchos_dif = []
        anchos_term = []
        
        for _, row in df_materiales.iterrows():
            cat = str(row['CAT']).strip().upper()
            
            if 'DIF' in cat:
                material, ancho = self._buscar_diferencial(row)
                if material:
                    materiales.append(material)
                    anchos_dif.extend([ancho] * material.cantidad)
            else:
                material, ancho = self._buscar_termica(row)
                if material:
                    materiales.append(material)
                    anchos_term.extend([ancho] * material.cantidad)
        
        logger.info(
            f"Protecciones procesadas: {len(anchos_dif)} dif, "
            f"{len(anchos_term)} term"
        )
        
        return materiales, anchos_dif, anchos_term
    
    def _buscar_diferencial(self, row) -> Tuple[Optional[Material], float]:
        """Busca diferencial en base de datos"""
        df_dif = self.datos['diferencial']
        
        sup_db = "SI" if str(row['SUP']).strip().upper() in ['SÍ', 'SI'] else "NO"
        
        match = df_dif[
            (df_dif['CANT POLOS'].astype(str) == str(row['POLOS']).strip()) &
            (df_dif['CORRIENTE'].astype(str) == str(row['AMP']).strip()) &
            (df_dif['FAMILIA'].astype(str) == str(row['FAM']).strip()) &
            (df_dif['SUPERINMUNIZADO'].astype(str) == sup_db)
        ]
        
        if match.empty:
            logger.warning(f"Diferencial no encontrado: {row.to_dict()}")
            return None, 0.0
        
        res = match.iloc[0]
        material = Material(
            codigo=str(res['CODIGO']),
            descripcion=str(res['DESCRIPCION']),
            cantidad=int(row['CANT']),
            categoria=TipoCategoria.DIFERENCIAL.value,
            ancho_mm=float(res['MEDIDA'])
        )
        
        return material, float(res['MEDIDA'])
    
    def _buscar_termica(self, row) -> Tuple[Optional[Material], float]:
        """Busca térmica en base de datos"""
        df_term = self.datos['termicas']
        
        match = df_term[
            (df_term['CANT POLOS'].astype(str) == str(row['POLOS']).strip()) &
            (df_term['CORRIENTE'].astype(str) == str(row['AMP']).strip()) &
            (df_term['FAMILIA'].astype(str) == str(row['FAM']).strip())
        ]
        
        if match.empty:
            logger.warning(f"Térmica no encontrada: {row.to_dict()}")
            return None, 0.0
        
        res = match.iloc[0]
        material = Material(
            codigo=str(res['CODIGO']),
            descripcion=str(res['DESCRIPCION']),
            cantidad=int(row['CANT']),
            categoria=TipoCategoria.TERMICA.value,
            ancho_mm=float(res['MEDIDA'])
        )
        
        return material, float(res['MEDIDA'])
    
    def _buscar_columna_contrafrente(
        self, 
        tipo_contrafrente: str, 
        df_acc: pd.DataFrame,
        tipo_tablero: TipoTablero
    ) -> Optional[str]:
        """
        Busca la columna de contrafrente mapeando el valor del bot a las columnas reales.
        
        El bot envía valores con guiones: 'abisagrado-calado', 'abisagrado-ciego', etc.
        
        Columnas reales en ESTANCO:
        - contrafrente abisagrado ciego
        - contrafrente abisagrado calado
        - contrafrente abulonado ciego
        - contrafrente abulonado calado
        
        Columnas reales en MODULAR:
        - CONTRAF CIEGO ABISAGRADO
        - CONTRAF ABULONADO CIEGO
        """
        
        # Convertir entrada del bot (ej: "abisagrado-calado") a palabras clave
        # Reemplazar guiones por espacios y normalizar
        entrada_normalizada = tipo_contrafrente.replace("-", " ").upper().strip()
        palabras_clave = entrada_normalizada.split()
        
        logger.debug(
            f"Buscando contrafrente: '{tipo_contrafrente}' → "
            f"Palabras clave: {palabras_clave} en {tipo_tablero.value}"
        )
        
        mejores_candidatos = []
        
        # Buscar en las columnas disponibles
        for col in df_acc.columns:
            col_upper = col.upper()
            
            # Contar coincidencias de palabras clave en esta columna
            coincidencias = sum(1 for palabra in palabras_clave if palabra in col_upper)
            
            # Solo considerar si tiene coincidencias significativas
            if coincidencias >= len(palabras_clave) - 1:  # Al menos 2 de 2, o 2 de 3, etc.
                mejores_candidatos.append((col, coincidencias))
        
        # Ordenar por número de coincidencias (descendente)
        mejores_candidatos.sort(key=lambda x: x[1], reverse=True)
        
        if mejores_candidatos:
            columna_encontrada = mejores_candidatos[0][0]
            logger.info(
                f"✅ Contrafrente mapeado correctamente: "
                f"'{tipo_contrafrente}' → '{columna_encontrada}'"
            )
            return columna_encontrada
        
        # Si no encuentra nada, intentar búsqueda más flexible
        logger.warning(
            f"⚠️ No se encontró coincidencia exacta para '{tipo_contrafrente}'. "
            f"Columnas disponibles: {list(df_acc.columns)}"
        )
        
        # Último intento: buscar cualquier coincidencia parcial
        for col in df_acc.columns:
            if 'CONTRAF' in col.upper() or 'CONTRAFRENTE' in col.upper():
                logger.warning(
                    f"⚠️ Usando columna de contrafrente por defecto: '{col}' "
                    f"(no fue posible mapear '{tipo_contrafrente}' con precisión)"
                )
                return col
        
        return None
    
    def procesar_accesorios(
        self,
        gabinete: Gabinete,
        tipo_contrafrente: str
    ) -> List[Material]:
        """Procesa accesorios del gabinete"""
        materiales = []
        
        tipo_tablero = TipoTablero(gabinete.tipo)
        df_acc = (
            self.datos['estanco'] 
            if tipo_tablero == TipoTablero.ESTANCO 
            else self.datos['modular']
        )
        
        col_id = 'GABINETE' if tipo_tablero == TipoTablero.ESTANCO else 'CODIGO'
        match = df_acc[
            df_acc[col_id].astype(str).str.strip() == gabinete.codigo
        ]
        
        if match.empty:
            logger.warning(f"Accesorios no encontrados para {gabinete.codigo}")
            return materiales
        
        row_acc = match.iloc[0]
        
        # Contrafrente (con búsqueda flexible y mapeo automático)
        col_contrafrente = self._buscar_columna_contrafrente(
            tipo_contrafrente, 
            df_acc, 
            tipo_tablero
        )
        
        if col_contrafrente:
            cod_cf = str(row_acc[col_contrafrente]).strip()
            if self._es_codigo_valido(cod_cf):
                materiales.append(Material(
                    codigo=cod_cf,
                    descripcion=self._obtener_descripcion(cod_cf, col_contrafrente),
                    cantidad=1,
                    categoria=TipoCategoria.ACCESORIO.value
                ))
            else:
                logger.warning(
                    f"Código de contrafrente inválido en columna '{col_contrafrente}': {cod_cf}"
                )
        else:
            logger.warning(
                f"No se pudo agregar contrafrente. "
                f"Parámetro del bot: '{tipo_contrafrente}'"
            )
        
        # Otros accesorios
        inicio = 7 if tipo_tablero == TipoTablero.ESTANCO else 2
        cols = list(df_acc.columns)
        
        for i in range(inicio, len(cols) - 1):
            if 'CANTIDAD' in cols[i + 1].upper():
                cod = str(row_acc[cols[i]]).strip()
                if self._es_codigo_valido(cod):
                    try:
                        cant = int(row_acc[cols[i + 1]])
                        materiales.append(Material(
                            codigo=cod,
                            descripcion=self._obtener_descripcion(cod, cols[i]),
                            cantidad=cant,
                            categoria=TipoCategoria.ACCESORIO.value
                        ))
                    except (ValueError, TypeError):
                        logger.warning(f"Cantidad inválida para accesorio {cod}")
        
        logger.info(f"Accesorios procesados: {len(materiales)}")
        return materiales
    
    @staticmethod
    def _es_codigo_valido(codigo: str) -> bool:
        """Verifica si un código es válido"""
        return codigo not in ['0', 'nan', 'No corresponde', 'No encontrado', '']
    
    def _obtener_descripcion(self, codigo: str, nombre_default: str) -> str:
        """Obtiene descripción desde diccionario maestro"""
        return self.dict_descripciones.get(
            codigo,
            f"Accesorio: {nombre_default}"
        )

logger = logging.getLogger(__name__)

class EscritorResultados:
    """Escribe resultados en el archivo Excel utilizando Pandas y OpenPyXL"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path

    def escribir_resumen(
        self,
        gabinete: Optional[any],
        rieles_usados: int,
        mensaje_error: Optional[str] = None
    ) -> str:
        """
        Genera el mensaje de resumen. 
        Nota: En modo Bot, no escribimos en B26, sino que devolvemos 
        el texto para que el Bot lo envíe por Telegram.
        """
        if mensaje_error:
            logger.error(mensaje_error)
            return f"❌ Error: {mensaje_error}"
        
        if gabinete:
            resumen = (
                f"✅ **TABLERO SELECCIONADO**\n"
                f"Gabinete: {gabinete.descripcion}\n"
                f"Cód: {gabinete.codigo}\n"
                f"Rieles: {rieles_usados}/{gabinete.cantidad_columnas}"
            )
            logger.info(f"Tablero seleccionado: {gabinete.descripcion}")
            return resumen
        
        logger.warning("No se encontró gabinete compatible")
        return "⚠️ SIN RESULTADOS: No hay gabinete compatible para esta configuración."

    def escribir_listado_materiales(self, materiales: List[any]):
        """Escribe el listado de materiales en la hoja 'LISTADO_MATERIALES' del Excel"""
        try:
            # 1. Convertir lista de objetos Material a DataFrame
            # Usamos una lista de diccionarios para que Pandas lo entienda
            datos = [
                {
                    'CODIGO': m.codigo,
                    'DESCRIPCION': m.descripcion,
                    'CANTIDAD': m.cantidad,
                    'CATEGORIA': m.categoria
                }
                for m in materiales
            ]
            df_nuevo = pd.DataFrame(datos)

            # 2. Guardar en el Excel sin borrar las otras hojas (Modo Append)
            # if_sheet_exists='replace' requiere openpyxl instalado
            with pd.ExcelWriter(
                self.file_path, 
                engine='openpyxl', 
                mode='a', 
                if_sheet_exists='replace'
            ) as writer:
                df_nuevo.to_excel(writer, sheet_name='LISTADO_MATERIALES', index=False)
            
            logger.info(f"Listado exportado a Excel: {len(materiales)} materiales")
            
        except PermissionError:
            error_msg = "Error: El archivo Excel está abierto en la PC. Cerralo para guardar el listado."
            logger.error(error_msg)
            raise Exception(error_msg)
        except Exception as e:
            logger.error(f"Error escribiendo listado con Pandas: {e}")
            raise


def ejecutar_dimensionamiento(config_input: dict, materiales_input: list):
  
    logger.info("=== INICIANDO ANÁLISIS TÉCNICO (PANDAS MODE) ===")
    
    try:
        # 1. Cargar datos (Usando la función que refactorizamos antes)
        # Esto devuelve un dict de DataFrames {'termicas': df, 'envolventes': df, ...}
        datos = cargar_datos() 
        
        # 2. Preparar Configuración y Materiales
        # Convertimos los inputs (dict) en los objetos que tu lógica ya usa
        config = ConfiguracionInput(**config_input)
        df_materiales_consulta = pd.DataFrame(materiales_input)
        
        # 3. Procesar materiales (Tu lógica de ingeniería se mantiene casi igual)
        procesador = ProcesadorMateriales(datos)
        
        # Seleccionador
        mat_sel, tipo_tablero_str, ancho_sel = procesador.procesar_seleccionador(
            config.seleccionador_ref
        )
        
        if not mat_sel:
            return "Error: Seleccionador no encontrado."

        tipo_tablero = TipoTablero(tipo_tablero_str)
        listado_materiales = [mat_sel]
        
        # Protecciones (Esta función dentro de tu procesador ahora debe usar Pandas)
        mats_prot, anchos_dif, anchos_term = procesador.procesar_protecciones_pandas(
            df_materiales_consulta
        )
        listado_materiales.extend(mats_prot)
        
        # 4. Calcular rieles y seleccionar gabinete
        calculador = CalculadorRieles(config)
        selector = SelectorGabinete(datos['envolventes'])
        
        gabinete = selector.seleccionar_gabinete(
            tipo_tablero,
            calculador,
            ancho_sel,
            anchos_dif,
            anchos_term
        )
        
        if not gabinete:
            return "❌ No se encontró un gabinete compatible."

        # Calcular rieles usados
        rieles_usados = calculador.calcular_rieles_necesarios(
            gabinete.largo_riel,
            ancho_sel,
            anchos_dif,
            anchos_term
        )
        
        # 5. Agregar gabinete y accesorios
        listado_materiales.append(Material(
            codigo=gabinete.codigo,
            descripcion=gabinete.descripcion,
            cantidad=1,
            categoria="GABINETE"
        ))
        
        accesorios = procesador.procesar_accesorios(gabinete, config.tipo_contrafrente)
        listado_materiales.extend(accesorios)
        
        # 6. ESCRITURA DE RESULTADOS (EL REEMPLAZO DE XLWINGS)
        
        # Creamos un DataFrame con el listado de materiales
        # Asumiendo que 'Material' es un objeto con atributos, usamos una lista de dicts
        df_final = pd.DataFrame([vars(m) for m in listado_materiales])
        
        # Guardamos en el Excel (Hoja "listado_materiales")
        # El engine 'openpyxl' es el que permite trabajar con .xlsx/.xlsm en Docker
        with pd.ExcelWriter(FILE_NAME, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            df_final.to_excel(writer, sheet_name='listado_materiales', index=False)
        
        logger.info("=== PROCESO FINALIZADO: Listado exportado a Excel ===")
        
        # Retornamos un resumen para que el Bot lo muestre en Telegram
        return f"✅ Éxito: Gabinete {gabinete.codigo} seleccionado. {len(listado_materiales)} materiales registrados."
        
    except Exception as e:
        logger.exception("Error crítico en el proceso")
        return f"❌ Error técnico: {str(e)}"


# if __name__ == "__main__":
#     ejecutar_dimensionamiento()