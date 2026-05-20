import os
import csv
import processing
# Importación de módulos necesarios de QGIS para procesamiento raster y vectorial
from qgis.PyQt.QtGui import ( QColor )
from qgis.analysis import ( QgsRasterCalculator, QgsRasterCalculatorEntry )
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterFileDestination,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsProject,
    QgsProcessingException,
)


# Clase principal que implementa el algoritmo personalizado para QGIS
class CreatePoints(QgsProcessingAlgorithm):
    # Identificadores de parámetros de entrada y salida
    NIR = 'TIF1' # Identificador para la imagen TIFF cercana al infrarrojo (NIR)
    RED = 'TIF2' # Identificador para la imagen TIFF banda roja (RED)
    OUTPUT = 'OUTPUT' # Identificador para el archivo de salida del NDVI
    OUTPUT_MASK = 'OUTPUT_MASK' # Identificador para el archivo de salida de la máscara binaria
    OUTPUT_VECTOR = 'OUTPUT_VECTOR' # Identificador para el archivo de salida del vector de la máscara

    def initAlgorithm(self, config=None):
        """
        Definición de los parámetros de entrada y salida del algoritmo.
        Se solicitan dos capas raster (NIR y RED) y tres archivos de salida (NDVI, máscara binaria y vector).
        """
        # Solicita raster TIFF NIR
        self.addParameter(
            QgsProcessingParameterRasterLayer( 
                self.NIR,
                'Imagen TIFF cercana al infrarrojo (NIR)'
            )
        )
        # Solicita raster TIFF RED
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.RED,
                'Imagen TIFF banda roja (RED)'
            )
        )
        # Solicita archivo de salida para NDVI
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                'Archivo de salida (NDVI)',
                fileFilter='GTiff (*.tif)',
                optional=True
            )
        )
        # Solicita archivo de salida para máscara binaria
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_MASK,
                'Archivo de salida (Máscara Binaria)',
                fileFilter='GTiff (*.tif)',
                optional=True
            )
        )
        # Solicita archivo de salida para vector de máscara
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_VECTOR,
                'Archivo de salida (Vector de Máscara)',
                fileFilter='GTiff (*.tif)',
                optional=True
            )
        )


    # Procesa las imágenes, calcula el NDVI, genera la máscara binaria, convierte a vectorial, limpia polígonos y calcula centroides
    def processAlgorithm(self, parameters, context, feedback):
        # Obtiene las capas raster de entrada
        nir_layer = self.parameterAsRasterLayer(parameters, self.NIR, context)
        red_layer = self.parameterAsRasterLayer(parameters, self.RED, context)
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        output_path_bm = self.parameterAsFileOutput(parameters, self.OUTPUT_MASK, context)
        output_path_vector = self.parameterAsFileOutput(parameters, self.OUTPUT_VECTOR, context)

        # Verifica que las capas se hayan cargado correctamente
        if nir_layer is None:
            raise QgsProcessingException('No se pudo cargar la capa NIR')
        if red_layer is None:
            raise QgsProcessingException('No se pudo cargar la capa RED')
        
        # Guarda el sistema de referencia para las demás capas
        source_crs = nir_layer.crs()
        
        # Si no se especifica ruta de salida, se usa una por defecto
        if not output_path:
            output_path = os.path.join(os.path.expanduser('~'), 'ndvi_output.tif')
            
        # Calcula el NDVI
        result_path = self.calculate_NDVI(nir_layer, red_layer, output_path, source_crs)

        ndvi_layer = QgsRasterLayer(result_path, 'NDVI')

        # Si no se especifica ruta de salida para la máscara, se usa una por defecto
        if not output_path_bm:
            output_path_bm = os.path.join(os.path.dirname(result_path), 'ndvi_mask.tif')
            
        # Calcula la máscara binaria
        result_path_bm = self.calculate_mask(ndvi_layer, output_path_bm, source_crs)
        # Convierte la máscara a vectorial y limpia polígonos
        cleaned_raster, cleaned_vector = self.mask_to_vector(result_path_bm, ndvi_layer, source_crs)
        # Calcula los centroides de los polígonos
        centroids_path = self.calculate_centroids(cleaned_vector, source_crs)

        # Devuelve los resultados principales
        return {self.OUTPUT: result_path, self.OUTPUT_MASK: cleaned_raster, self.OUTPUT_VECTOR: cleaned_vector}

    def calculate_NDVI(self, nir_layer: QgsRasterLayer, red_layer: QgsRasterLayer, output_path: str, source_crs):
        """
        Calcula el NDVI usando las bandas NIR y RED y guarda el resultado en un archivo raster.
        """
        # Se cargan las imágenes a la calculadora raster
        nir_entry = QgsRasterCalculatorEntry()
        nir_entry.raster = nir_layer
        nir_entry.ref = 'nir@1'
        nir_entry.bandNumber = 1

        red_entry = QgsRasterCalculatorEntry()
        red_entry.raster = red_layer
        red_entry.ref = 'red@1'
        red_entry.bandNumber = 1

        entries = [nir_entry, red_entry]

        # Se guardan las propiedades de una de las imágenes
        extent = nir_layer.extent()
        width = nir_layer.width()
        height = nir_layer.height()
        # Expresión del NDVI
        expression = '(nir@1 - red@1) / (nir@1 + red@1 + 1e-10)'

        # Se realiza el cálculo raster
        calc = QgsRasterCalculator(expression, output_path, 'GTiff', extent, width, height, entries)
        result = calc.processCalculation()

        # Verifica si hubo error en el cálculo
        if result != 0:
            raise QgsProcessingException(f'Error al calcular NDVI, código: {result}')

        # Carga el raster NDVI generado y lo agrega al proyecto
        ndvi_layer = QgsRasterLayer(output_path, 'NDVI')
        if ndvi_layer.isValid():
            ndvi_layer.setCrs(source_crs)
            QgsProject.instance().addMapLayer(ndvi_layer)

        return output_path
    
    # Cálculo de la máscara binaria según la condición dada
    def calculate_mask(self, ndvi_layer: QgsRasterLayer, output_path: str, source_crs):
        """
        Genera una máscara binaria a partir del raster NDVI usando una expresión lógica.
        """
        bMask_entry = QgsRasterCalculatorEntry()
        bMask_entry.raster = ndvi_layer
        bMask_entry.ref = 'ndvi@1'
        bMask_entry.bandNumber = 1

        entries = [bMask_entry]

        extent = ndvi_layer.extent()
        width = ndvi_layer.width()
        height = ndvi_layer.height()

        # Expresión para definir los valores válidos de NDVI
        expression = '(ndvi@1 < 0.333) AND (0.12 < ndvi@1)'

        # Se realiza el cálculo raster para la máscara
        calc = QgsRasterCalculator(expression, output_path, 'GTiff', extent, width, height, entries)
        result = calc.processCalculation()

        # Verifica si hubo error en el cálculo
        if result != 0:
            raise QgsProcessingException(f'Error al calcular máscara binaria, código: {result}')
        
        return output_path
    
    # Convierte máscara binaria a vectorial y limpia polígonos según área
    def mask_to_vector(self, mask_path: str, ndvi_layer: QgsRasterLayer, source_crs):
        """
        Convierte la máscara binaria a vectorial, calcula el área de los polígonos y filtra por tamaño.
        """
        # Convierte la máscara raster a vectorial (polígonos)
        mask_vector = os.path.splitext(mask_path)[0] + "_vector.gpkg"
        processing.run("gdal:polygonize", {
            'INPUT': mask_path,
            'BAND': 1,
            'FIELD': 'value',
            'EIGHT_CONNECTEDNESS': False,
            'OUTPUT': mask_vector
        })

        # Calcula el área de cada polígono
        mask_with_area = os.path.splitext(mask_path)[0] + "_area.gpkg"
        processing.run("native:fieldcalculator", {
            'INPUT': mask_vector,
            'FIELD_NAME': 'area_m2',
            'FIELD_TYPE': 0,  # decimal
            'FIELD_LENGTH': 20,
            'FIELD_PRECISION': 3,
            'FORMULA': '$area',
            'OUTPUT': mask_with_area
        })

        # Define el área mínima y máxima para filtrar polígonos
        min_area = 50
        max_area = 500

        # Extrae solo los polígonos que cumplen con el área y valor
        cleaned_vector = os.path.splitext(mask_path)[0] + "_cleaned.gpkg"
        processing.run("native:extractbyexpression", {
            'INPUT': mask_with_area,
            'EXPRESSION': f'"value" = 1 AND "area_m2" >= {min_area} AND "area_m2" <= {max_area}',
            'OUTPUT': cleaned_vector
        })
        calculated_vector = QgsVectorLayer(cleaned_vector, 'Mask_Cleaned', 'ogr')
        if calculated_vector.isValid():
            calculated_vector.setCrs(source_crs)

        # Rasteriza el vector limpio para obtener una nueva máscara
        extent = ndvi_layer.extent()
        cleaned_raster = os.path.splitext(mask_path)[0] + "_cleaned.tif"
        processing.run("gdal:rasterize", {
            'INPUT': cleaned_vector,
            'FIELD': 'value',
            'UNITS': 1,
            'WIDTH': ndvi_layer.rasterUnitsPerPixelX(),
            'HEIGHT': ndvi_layer.rasterUnitsPerPixelY(),
            'EXTENT': extent,
            'NODATA': 0,
            'DATA_TYPE': 5, 
            'OUTPUT': cleaned_raster
        })

        # Carga la máscara raster limpia
        cleaned_layer = QgsRasterLayer(cleaned_raster, 'Binary_Mask_Cleaned')

        if cleaned_layer.isValid():
            cleaned_layer.setCrs(source_crs)
            QgsProject.instance().addMapLayer(cleaned_layer)
        else:
            raise QgsProcessingException("No se pudo cargar la máscara limpiada.")
        
        # Agrega el vector limpio al proyecto
        if calculated_vector.isValid():
            QgsProject.instance().addMapLayer(calculated_vector)
        else: 
            raise QgsProcessingException("No se pudo cargar el vector calculado.")

        return cleaned_raster, cleaned_vector

    # Cálculo de los centroides usando las herramientas nativas de QGIS
    def calculate_centroids(self, vector_path: str, source_crs):
        """
        Calcula los centroides de los polígonos del vector limpio y los guarda en un archivo.
        """
        centroids_path = os.path.splitext(vector_path)[0] + "_centroids.gpkg"
        processing.run("native:centroids", {
            'INPUT': vector_path,
            'OUTPUT': centroids_path
        })
        centroids_layer = QgsVectorLayer(centroids_path, 'Centroids', 'ogr')
        if centroids_layer.isValid():
            centroids_layer.setCrs(source_crs)
            QgsProject.instance().addMapLayer(centroids_layer)
        else:
            raise QgsProcessingException("No se pudo cargar el layer de centroides.")
        return centroids_path

    # Nombre interno del algoritmo
    def name(self):
        return 'calcular_ndvi'

    # Nombre visible del algoritmo en QGIS
    def displayName(self):
        return 'Calculo de NDVI y generación de puntos'

    # Grupo al que pertenece el algoritmo
    def group(self):
        return 'Herramientas personalizadas'

    # Identificador del grupo
    def groupId(self):
        return 'herramientas_personalizadas'

    # Método necesario para crear una nueva instancia del algoritmo
    def createInstance(self):
        return CreatePoints()
