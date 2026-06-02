import os
import tempfile

from osgeo import gdal, osr

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterFileDestination,
    QgsProcessingException
)

import processing


class GeoreferenceAndExecuteNDVI(QgsProcessingAlgorithm):

    WIDTH_METERS = 'WIDTH_METERS'
    HEIGHT_METERS = 'HEIGHT_METERS'

    EPSG = 'EPSG'

    ORIGIN_X = 'ORIGIN_X'
    ORIGIN_Y = 'ORIGIN_Y'

    NIR = 'NIR'
    RED = 'RED'

    MIN_AREA = 'MIN_AREA'
    MAX_AREA = 'MAX_AREA'

    OUTPUT = 'OUTPUT'
    OUTPUT_MASK = 'OUTPUT_MASK'
    OUTPUT_VECTOR = 'OUTPUT_VECTOR'

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterNumber(
                self.WIDTH_METERS,
                'Tamaño eje X de la imagen (m)',
                QgsProcessingParameterNumber.Double,
                200.0,
                False,
                0.0001
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.HEIGHT_METERS,
                'Tamaño eje Y de la imagen (m)',
                QgsProcessingParameterNumber.Double,
                150.0,
                False,
                0.0001
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.EPSG,
                'EPSG',
                defaultValue='32613'
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.ORIGIN_X,
                'Coordenada X origen',
                QgsProcessingParameterNumber.Double,
                0.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.ORIGIN_Y,
                'Coordenada Y origen',
                QgsProcessingParameterNumber.Double,
                0.0
            )
        )

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
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_AREA,
                'Área mínima (m²)',
                QgsProcessingParameterNumber.Double,
                50.0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_AREA,
                'Área máxima (m²)',
                QgsProcessingParameterNumber.Double,
                500.0
            )
        )

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
                fileFilter='GPKG (*.gpkg)',
                optional=True
            )
        )

    def processAlgorithm(self, parameters, context, feedback):

        width_meters = self.parameterAsDouble(
            parameters,
            self.WIDTH_METERS,
            context
        )

        height_meters = self.parameterAsDouble(
            parameters,
            self.HEIGHT_METERS,
            context
        )

        epsg_code = self.parameterAsString(
            parameters,
            self.EPSG,
            context
        )

        origin_x = self.parameterAsDouble(
            parameters,
            self.ORIGIN_X,
            context
        )

        origin_y = self.parameterAsDouble(
            parameters,
            self.ORIGIN_Y,
            context
        )

        min_area = self.parameterAsDouble(
            parameters,
            self.MIN_AREA,
            context
        )

        max_area = self.parameterAsDouble(
            parameters,
            self.MAX_AREA,
            context
        )

        nir_layer = self.parameterAsRasterLayer(
            parameters,
            self.NIR,
            context
        )

        red_layer = self.parameterAsRasterLayer(
            parameters,
            self.RED,
            context
        )

        if nir_layer is None:
            raise QgsProcessingException(
                'No se pudo cargar la imagen NIR'
            )

        if red_layer is None:
            raise QgsProcessingException(
                'No se pudo cargar la imagen RED'
            )

        nir_temp = os.path.join(
            tempfile.gettempdir(),
            'nir_georef.tif'
        )

        red_temp = os.path.join(
            tempfile.gettempdir(),
            'red_georef.tif'
        )

        self.georeference_tif(
            nir_layer.source(),
            nir_temp,
            width_meters,
            height_meters,
            epsg_code,
            origin_x,
            origin_y
        )

        self.georeference_tif(
            red_layer.source(),
            red_temp,
            width_meters,
            height_meters,
            epsg_code,
            origin_x,
            origin_y
        )

        result = processing.run(
            "script:calcular_ndvi",
            {
                'TIF1': nir_temp,
                'TIF2': red_temp,

                'MIN_AREA': min_area,
                'MAX_AREA': max_area,

                'OUTPUT': parameters[self.OUTPUT],
                'OUTPUT_MASK': parameters[self.OUTPUT_MASK],
                'OUTPUT_VECTOR': parameters[self.OUTPUT_VECTOR]
            },
            context=context,
            feedback=feedback
        )

        return result

    def georeference_tif(
        self,
        input_tif,
        output_tif,
        width_meters,
        height_meters,
        epsg_code,
        origin_x,
        origin_y
    ):

        dataset = gdal.Open(input_tif)

        if dataset is None:
            raise QgsProcessingException(
                f'No se pudo abrir {input_tif}'
            )

        cols = dataset.RasterXSize
        rows = dataset.RasterYSize

        pixel_width = width_meters / cols
        pixel_height = height_meters / rows

        driver = gdal.GetDriverByName('GTiff')

        output_ds = driver.CreateCopy(
            output_tif,
            dataset,
            0
        )

        geotransform = (
            origin_x,
            pixel_width,
            0.0,
            origin_y,
            0.0,
            -pixel_height
        )

        output_ds.SetGeoTransform(
            geotransform
        )

        spatial_ref = osr.SpatialReference()

        spatial_ref.ImportFromEPSG(
            int(epsg_code)
        )

        output_ds.SetProjection(
            spatial_ref.ExportToWkt()
        )

        output_ds.FlushCache()

        output_ds = None
        dataset = None

    def name(self):
        return 'georeference_and_execute_ndvi'

    def displayName(self):
        return 'Georreferenciar TIFF y ejecutar NDVI'

    def group(self):
        return 'Herramientas personalizadas'

    def groupId(self):
        return 'herramientas_personalizadas'

    def createInstance(self):
        return GeoreferenceAndExecuteNDVI()