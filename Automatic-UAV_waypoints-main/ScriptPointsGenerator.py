import os
import csv
import processing
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

class CreatePoints(QgsProcessingAlgorithm):
    NIR = 'TIF1' # Identificador para la imagen TIFF cercana al infrarrojo (NIR)
    RED = 'TIF2' # Identificador para la imagen TIFF banda roja (RED)
    OUTPUT = 'OUTPUT' # Identificador para el archivo de salida del NDVI
    OUTPUT_MASK = 'OUTPUT_MASK' # Identificador para el archivo de salida de la máscara binaria
    OUTPUT_VECTOR = 'OUTPUT_VECTOR' # Identificador para el archivo de salida del vector de la máscara

    def initAlgorithm(self, config=None): # Se definen los parámetros de entrada y salida del algoritmo
        # se solicitan raster TIFF NIR y RED 
        self.addParameter(
            QgsProcessingParameterRasterLayer( 
                self.NIR,
                'Imagen TIFF cercana al infrarrojo (NIR)'
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.RED,
                'Imagen TIFF banda roja (RED)'
            )
        )

        # se solicitan archivos de salida para el NDVI, la máscara binaria y el vector de la máscara
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                'Archivo de salida (NDVI)',
                fileFilter='GTiff (*.tif)',
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_MASK,
                'Archivo de salida (Máscara Binaria)',
                fileFilter='GTiff (*.tif)',
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_VECTOR,
                'Archivo de salida (Vector de Máscara)',
                fileFilter='GTiff (*.tif)',
                optional=True
            )
        )

    #aqui ya se procesan las imágenes, se calcula el NDVI, se genera la máscara binaria, se convierte a vectorial, se limpian los polígonos según el área y se calculan los centroides


    def processAlgorithm(self, parameters, context, feedback):
        nir_layer = self.parameterAsRasterLayer(parameters, self.NIR, context)
        red_layer = self.parameterAsRasterLayer(parameters, self.RED, context)
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        output_path_bm = self.parameterAsFileOutput(parameters, self.OUTPUT_MASK, context)
        output_path_vector = self.parameterAsFileOutput(parameters, self.OUTPUT_VECTOR, context)

        if nir_layer is None:
            raise QgsProcessingException('No se pudo cargar la capa NIR')
        if red_layer is None:
            raise QgsProcessingException('No se pudo cargar la capa RED')
        
        # Se guarda el sistema de referencia para las demás capas
        source_crs = nir_layer.crs()
        
        if not output_path:
            output_path = os.path.join(os.path.expanduser('~'), 'ndvi_output.tif')
            
        result_path = self.calculate_NDVI(nir_layer, red_layer, output_path, source_crs)

        ndvi_layer = QgsRasterLayer(result_path, 'NDVI')

        if not output_path_bm:
            output_path_bm = os.path.join(os.path.dirname(result_path), 'ndvi_mask.tif')
            
        result_path_bm = self.calculate_mask(ndvi_layer, output_path_bm, source_crs)
        cleaned_raster, cleaned_vector = self.mask_to_vector(result_path_bm, ndvi_layer, source_crs)
        centroids_path = self.calculate_centroids(cleaned_vector, source_crs)


        return {self.OUTPUT: result_path, self.OUTPUT_MASK: cleaned_raster, self.OUTPUT_VECTOR: cleaned_vector}

    def calculate_NDVI(self, nir_layer: QgsRasterLayer, red_layer: QgsRasterLayer, output_path: str, source_crs):
    # se cargan las imagenes a la calculadora raster
        nir_entry = QgsRasterCalculatorEntry()
        nir_entry.raster = nir_layer
        nir_entry.ref = 'nir@1'
        nir_entry.bandNumber = 1

        red_entry = QgsRasterCalculatorEntry()
        red_entry.raster = red_layer
        red_entry.ref = 'red@1'
        red_entry.bandNumber = 1

        entries = [nir_entry, red_entry]

    # se guardan las propiedades de una de las imagenes
        extent = nir_layer.extent()
        width = nir_layer.width()
        height = nir_layer.height()
    #expresion del NDVI
        expression = '(nir@1 - red@1) / (nir@1 + red@1 + 1e-10)'

        calc = QgsRasterCalculator(expression, output_path, 'GTiff', extent, width, height, entries)
        result = calc.processCalculation()

        if result != 0:
            raise QgsProcessingException(f'Error al calcular NDVI, código: {result}')

        ndvi_layer = QgsRasterLayer(output_path, 'NDVI')
        if ndvi_layer.isValid():
            ndvi_layer.setCrs(source_crs)
            QgsProject.instance().addMapLayer(ndvi_layer)

        return output_path
    
    # Calculo de la máscara binaria segun la condicion dada
    def calculate_mask(self, ndvi_layer: QgsRasterLayer, output_path: str, source_crs):
        bMask_entry = QgsRasterCalculatorEntry()
        bMask_entry.raster = ndvi_layer
        bMask_entry.ref = 'ndvi@1'
        bMask_entry.bandNumber = 1

        entries = [bMask_entry]

        extent = ndvi_layer.extent()
        width = ndvi_layer.width()
        height = ndvi_layer.height()

        expression = '(ndvi@1 < 0.333) AND (0.12 < ndvi@1)'

        calc = QgsRasterCalculator(expression, output_path, 'GTiff', extent, width, height, entries)
        result = calc.processCalculation()

        if result != 0:
            raise QgsProcessingException(f'Error al calcular máscara binaria, código: {result}')
        
        return output_path
    
    # Convertir máscara binaria a vectorial y limpiar polígonos según área
    def mask_to_vector(self, mask_path: str, ndvi_layer: QgsRasterLayer, source_crs):

        mask_vector = os.path.splitext(mask_path)[0] + "_vector.gpkg"
        processing.run("gdal:polygonize", {
            'INPUT': mask_path,
            'BAND': 1,
            'FIELD': 'value',
            'EIGHT_CONNECTEDNESS': False,
            'OUTPUT': mask_vector
        })

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

        min_area = 50
        max_area = 500

        cleaned_vector = os.path.splitext(mask_path)[0] + "_cleaned.gpkg"
        processing.run("native:extractbyexpression", {
            'INPUT': mask_with_area,
            'EXPRESSION': f'"value" = 1 AND "area_m2" >= {min_area} AND "area_m2" <= {max_area}',
            'OUTPUT': cleaned_vector
        })
        calculated_vector = QgsVectorLayer(cleaned_vector, 'Mask_Cleaned', 'ogr')
        if calculated_vector.isValid():
            calculated_vector.setCrs(source_crs)

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

        cleaned_layer = QgsRasterLayer(cleaned_raster, 'Binary_Mask_Cleaned')

        if cleaned_layer.isValid():
            cleaned_layer.setCrs(source_crs)
            QgsProject.instance().addMapLayer(cleaned_layer)
        else:
            raise QgsProcessingException("No se pudo cargar la máscara limpiada.")
        
        if calculated_vector.isValid():
            QgsProject.instance().addMapLayer(calculated_vector)
        else: 
            raise QgsProcessingException("No se pudo cargar el vector calculado.")

        return cleaned_raster, cleaned_vector

    # Calculo de los centroides usando las herramientas nativas
    def calculate_centroids(self, vector_path: str, source_crs):
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

    def name(self):
        return 'calcular_ndvi'

    def displayName(self):
        return 'Calculo de NDVI y generación de puntos'

    def group(self):
        return 'Herramientas personalizadas'

    def groupId(self):
        return 'herramientas_personalizadas'

    def createInstance(self):
        return CreatePoints()
