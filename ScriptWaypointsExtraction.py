"""
Script de procesamiento para exportar los vértices de una capa de polígonos
a un archivo CSV con coordenadas lat/lon redondeadas a una precisión específica.
"""


import os
import csv
import operator
from functools import reduce

import shapely

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QFont, QColor
from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFileDestination,
    QgsVectorFileWriter,
    QgsProcessing,
    QgsProcessingContext,
    QgsVectorLayer,
    QgsPointXY,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsTextBufferSettings
)
import processing 

COORDINATE_PRECISION = 8 

class ExportVertices(QgsProcessingAlgorithm): 
    POLYGON = 'POLYGON'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        """
        Define y configura los parámetros de entrada y salida del algoritmo.

        Este método es llamado automáticamente por QGIS al cargar el algoritmo.
        Su función es declarar qué datos necesita el proceso para ejecutarse,
        así como los tipos de entrada y salida que manejará.

        En este caso, se definen dos parámetros:
        - Una capa vectorial de tipo polígono (entrada).
        - Un archivo CSV donde se exportarán los resultados (salida).

        Parameters
        ----------
        config : dict, optional
            Configuración adicional del algoritmo (no utilizada en este caso).

        Funcionalidad
        -------------
        - Registra un parámetro de entrada que acepta únicamente capas de polígonos.
        - Registra un parámetro de salida que define la ruta del archivo CSV generado.

        Métodos utilizados
        ------------------
        - self.addParameter()
        - QgsProcessingParameterFeatureSource()
        - QgsProcessingParameterFileDestination()
        """   
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.POLYGON,
                'Capa de polígonos',
                [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                'Archivo CSV de salida',
                fileFilter='CSV (*.csv)'
            )
        )

    def extract_vertices(self, polygon, context):
        """
        Extrae los vértices de una capa de polígonos utilizando una herramienta
        nativa de procesamiento de QGIS.

        Este método ejecuta el algoritmo interno `native:extractvertices` mediante
        la API de procesamiento de QGIS. El resultado es una nueva capa vectorial
        de tipo punto donde cada punto corresponde a un vértice del polígono
        original.

        Parameters
        ----------
        polygon : QgsFeatureSource o QgsVectorLayer
            Capa de entrada que contiene los polígonos de los cuales se desean
            extraer los vértices.

        context : QgsProcessingContext
            Contexto de ejecución del algoritmo dentro de QGIS, utilizado para
            gestionar la ejecución de herramientas de procesamiento.

        Returns
        -------
        QgsVectorLayer
            Capa temporal en memoria que contiene los vértices extraídos como
            entidades puntuales.

        Funcionalidad
        -------------
        - Ejecuta el algoritmo nativo de QGIS `native:extractvertices`.
        - Genera una capa temporal de puntos donde cada punto representa un
        vértice de la geometría del polígono original.
        - Devuelve dicha capa para ser procesada posteriormente por otros
        métodos del algoritmo.

        Métodos utilizados
        ------------------
        - processing.run()
        """   
        return processing.run("native:extractvertices", {
            'INPUT': polygon,
            'OUTPUT': 'memory:vertices'
        }, context=context)['OUTPUT']

    def add_fields(self, layer):
        """
        Añade campos de atributos a la capa de vértices.

        Este método modifica la estructura de atributos de la capa vectorial
        generada tras la extracción de vértices, agregando nuevos campos donde
        se almacenarán las coordenadas geográficas, la altitud y el orden de
        cada vértice.

        Los campos añadidos permiten estructurar la información necesaria para
        la posterior exportación a CSV y la generación de waypoints utilizados
        en misiones de dron.

        Parameters
        ----------
        layer : QgsVectorLayer
            Capa vectorial de tipo punto que contiene los vértices extraídos
            del polígono original.

        Returns
        -------
        None

        Funcionalidad
        -------------
        - Accede al proveedor de datos de la capa (`dataProvider`).
        - Añade cuatro nuevos campos de atributos:
            * lon : longitud del vértice.
            * lat : latitud del vértice.
            * alt : altitud asociada al punto.
            * orden : índice secuencial del vértice.
        - Actualiza la definición de campos de la capa para que los cambios
        sean reconocidos por QGIS.

        Métodos utilizados
        ------------------
        - layer.dataProvider()
        - addAttributes()
        - layer.updateFields()
        - QgsField()
        """
        layer.dataProvider().addAttributes([
            QgsField("lon", QVariant.Double),
            QgsField("lat", QVariant.Double),
            QgsField("alt", QVariant.Double),
            QgsField("orden", QVariant.Int)
        ])
        layer.updateFields()

    def assign_vertex_attributes(self, layer):
        """
        Asigna valores a los campos de atributos de cada vértice.

        Este método recorre todas las entidades de la capa de vértices y
        calcula sus coordenadas geográficas a partir de la geometría del punto.
        Posteriormente, guarda estos valores en los campos previamente creados
        (lon, lat, alt, orden).

        Además, se asigna un índice secuencial que permite mantener el orden
        de los vértices dentro del conjunto de datos.

        Parameters
        ----------
        layer : QgsVectorLayer
            Capa vectorial de tipo punto que contiene los vértices extraídos
            del polígono.

        Returns
        -------
        None

        Funcionalidad
        -------------
        - Inicia una sesión de edición en la capa.
        - Itera sobre cada entidad (vértice) presente en la capa.
        - Obtiene las coordenadas del punto a partir de su geometría.
        - Asigna los valores correspondientes a los campos:
            * lon : longitud del punto.
            * lat : latitud del punto.
            * alt : altitud fija asignada al vértice.
            * orden : número secuencial del vértice.
        - Guarda los cambios en la capa.

        Métodos utilizados
        ------------------
        - layer.getFeatures()
        - feature.geometry()
        - asPoint()
        - layer.startEditing()
        - layer.updateFeature()
        - layer.commitChanges()

        Notas
        -----
        Este paso es necesario para preparar los datos antes de exportarlos
        a un archivo CSV y utilizarlos posteriormente en la generación de
        waypoints para la misión de dron.
        """ 
        lon_idx = layer.fields().indexFromName("lon")
        lat_idx = layer.fields().indexFromName("lat")
        alt_idx = layer.fields().indexFromName("alt")
        orden_idx = layer.fields().indexFromName("orden")
        for i, feat in enumerate(layer.getFeatures()):
            pt = feat.geometry().asPoint()
            layer.dataProvider().changeAttributeValues({
                feat.id(): {
                    lon_idx: round(pt.x(), COORDINATE_PRECISION),
                    lat_idx: round(pt.y(), COORDINATE_PRECISION),
                    alt_idx: 20.0,
                    orden_idx: i
                }
            })

    def export_to_csv(self, layer, output_csv):
        """
        Exporta la capa de vértices a un archivo CSV.

        Este método guarda la información contenida en la capa de vértices
        (geometría y atributos) en un archivo CSV externo. El archivo generado
        contendrá las coordenadas y atributos previamente asignados a cada
        vértice, permitiendo su uso posterior en procesos de análisis,
        generación de waypoints o integración con otros sistemas.

        Parameters
        ----------
        layer : QgsVectorLayer
            Capa vectorial de tipo punto que contiene los vértices y sus
            atributos asociados.

        output_csv : str
            Ruta del archivo CSV donde se guardarán los datos exportados.

        Returns
        -------
        None

        Funcionalidad
        -------------
        - Utiliza el sistema de escritura de capas vectoriales de QGIS.
        - Exporta los atributos y coordenadas de la capa a formato CSV.
        - Guarda el archivo en la ruta especificada por el usuario.

        Métodos utilizados
        ------------------
        - QgsVectorFileWriter.writeAsVectorFormat()
        
        Notas
        -----
        El archivo CSV generado servirá posteriormente como base para la
        generación de waypoints y la creación del plan de misión del dron.
        """     
        QgsVectorFileWriter.writeAsVectorFormat(
            layer,
            output_csv,
            "UTF-8",
            layer.crs(),
            "CSV",
            False,
            ["GEOMETRY=AS_XY"]
        )

    def resolve_csv_path(self, output_csv):
        """
        Resuelve la ruta real del archivo CSV generado.

        Algunos procesos de exportación en QGIS pueden modificar la ruta o el
        nombre del archivo generado. Este método verifica y ajusta la ruta del
        archivo CSV para asegurar que las siguientes etapas del algoritmo
        trabajen con el archivo correcto.

        Parameters
        ----------
        output_csv : str
            Ruta inicial del archivo CSV generada durante el proceso de
            exportación.

        Returns
        -------
        str
            Ruta final válida del archivo CSV que será utilizada por los
            siguientes pasos del algoritmo.

        Funcionalidad
        -------------
        - Verifica si el archivo CSV generado corresponde a la ruta esperada.
        - Ajusta la ruta si el sistema de exportación de QGIS generó una
        variación del nombre o extensión.
        - Devuelve la ruta final que se utilizará en el resto del flujo
        del algoritmo.

        Notas
        -----
        Este paso garantiza que los métodos posteriores (filtrado de campos,
        generación de waypoints y creación de capas en QGIS) trabajen con
        el archivo CSV correcto.
        """ 
        if not os.path.exists(output_csv):
            base, ext = os.path.splitext(output_csv)
            if ext.lower() != ".csv" and os.path.exists(base + ".csv"):
                return base + ".csv"
        return output_csv

    def filter_csv_fields(self, output_csv, fields):
        """
        Filtra las columnas de un archivo CSV para conservar únicamente
        los campos especificados.

        Este método lee el archivo CSV generado previamente y elimina
        todas las columnas que no formen parte de la lista de campos
        requeridos. El resultado es un archivo CSV simplificado que
        contiene solo la información necesaria para la generación de
        waypoints y planes de misión.

        Parameters
        ----------
        csv_file_path : str
            Ruta del archivo CSV que será procesado.

        fields : list of str
            Lista de nombres de columnas que deben conservarse
            en el archivo final.

        Returns
        -------
        None

        Funcionalidad
        -------------
        - Lee el archivo CSV original.
        - Selecciona únicamente las columnas indicadas.
        - Elimina campos adicionales generados por QGIS durante la exportación.
        - Sobrescribe el archivo con la estructura filtrada.

        Notas
        -----
        Este paso es necesario porque la exportación inicial de QGIS
        puede incluir atributos adicionales que no son relevantes
        para el procesamiento posterior del algoritmo.

        Los campos típicamente conservados son:
        - lon : longitud del punto.
        - lat : latitud del punto.
        - alt : altitud asignada al waypoint.
        - orden : índice secuencial del punto.
        """ 
        temp_csv = output_csv + ".tmp"
        with open(output_csv, newline='', encoding="utf-8") as infile, \
             open(temp_csv, 'w', newline='', encoding="utf-8") as outfile:
            reader = csv.DictReader(infile)
            writer = csv.DictWriter(outfile, fieldnames=fields)
            writer.writeheader()
            for row in reader:
                writer.writerow({k: row[k] for k in fields})
        os.replace(temp_csv, output_csv)

    def add_csv_layer_to_project(self, csv_path, layer_name):
        """
        Añade un archivo CSV como capa vectorial de puntos dentro del proyecto de QGIS.

        Este método carga un archivo CSV que contiene coordenadas geográficas
        (longitud y latitud) y lo convierte en una capa vectorial de puntos
        visible dentro del proyecto actual de QGIS.

        Parameters
        ----------
        csv_path : str
            Ruta del archivo CSV que contiene las coordenadas de los puntos.

        layer_name : str
            Nombre que se asignará a la capa dentro del proyecto de QGIS.

        Returns
        -------
        None

        Funcionalidad
        -------------
        - Interpreta el archivo CSV como una capa de puntos utilizando
        las columnas de coordenadas.
        - Crea una capa vectorial a partir del archivo.
        - Añade la capa al proyecto activo de QGIS para su visualización
        y análisis.

        Métodos utilizados
        ------------------
        - QgsVectorLayer()
        - QgsProject.instance().addMapLayer()

        Notas
        -----
        Este método permite visualizar directamente en el mapa los puntos
        almacenados en el CSV, como los vértices del polígono o los
        waypoints generados durante el procesamiento.
        """ 
        csv_layer = QgsVectorLayer(
            path=csv_path,
            baseName=layer_name,
            providerLib="ogr"
        )
        if csv_layer.isValid():
            QgsProject.instance().addMapLayer(csv_layer)

    def generate_waypoints(self, output_csv): 
        waypoints = get_waypoints_from_polygon(output_csv)
        waypoints_csv = os.path.splitext(output_csv)[0] + "_waypoints.csv"
        write_waypoints_on_csv(waypoints, waypoints_csv)
        return waypoints, waypoints_csv

    def add_waypoints_to_qgis(self, waypoints, crs, base_name):
        # Puntos
        point_layer_name = f"{base_name}_waypoints_points"
        point_layer = QgsVectorLayer(f"Point?crs={crs.authid()}", point_layer_name, "memory")
        pr = point_layer.dataProvider()
        pr.addAttributes([
            QgsField("orden", QVariant.Int),
            QgsField("lon", QVariant.Double),
            QgsField("lat", QVariant.Double)
        ])
        point_layer.updateFields()

        feats = []
        for i, (lon, lat) in enumerate(waypoints):
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            feat.setAttributes([i, lon, lat])
            feats.append(feat)
        pr.addFeatures(feats)
        point_layer.updateExtents()
        QgsProject.instance().addMapLayer(point_layer)

        # Etiquetado
        text_format = QgsTextFormat()
        text_format.setFont(QFont("Arial", 14, QFont.Bold))
        text_format.setSize(14)
        text_format.setColor(QColor("yellow"))
        buffer_settings = QgsTextBufferSettings()
        buffer_settings.setEnabled(True)
        buffer_settings.setSize(2)
        buffer_settings.setColor(QColor("black"))
        text_format.setBuffer(buffer_settings)
        labeling = QgsPalLayerSettings()
        labeling.fieldName = "orden"
        labeling.enabled = True
        labeling.setFormat(text_format)
        point_layer.setLabelsEnabled(True)
        point_layer.setLabeling(QgsVectorLayerSimpleLabeling(labeling))
        point_layer.triggerRepaint()

        # Línea
        if len(waypoints) > 1:
            line_layer_name = f"{base_name}_waypoints_route"
            line_layer = QgsVectorLayer(f"LineString?crs={crs.authid()}", line_layer_name, "memory")
            prl = line_layer.dataProvider()
            prl.addAttributes([QgsField("orden", QVariant.Int)])
            line_layer.updateFields()
            line_feat = QgsFeature()
            line_feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(lon, lat) for lon, lat in waypoints]))
            line_feat.setAttributes([0])
            prl.addFeature(line_feat)
            line_layer.updateExtents()
            QgsProject.instance().addMapLayer(line_layer)
    
    def write_mission_plan(self, waypoints, output_csv): 
        mission_plan_txt = os.path.splitext(output_csv)[0] + "_mission_plan.txt"
        with open(mission_plan_txt, 'w', newline='') as file:
            file.write('QGC WPL 110\n')

            def get_string_of_tab_separated_values(*args):
                ret = ''
                for s in args:
                    ret = ret + str(s) + '\t'
                return ret

            for i in range(len(waypoints)):
                index = i
                current_wp = 1 if i == 0 else 0
                coord_frame = 0 if i == 0 else 3
                command = 16
                param1, param2, param3, param4 = 0, 0, 0, 0
                longitude, latitude = waypoints[i]
                altitude = 13 if i == 0 else 45
                autocontinue = 1
                file.write(
                    get_string_of_tab_separated_values(
                        index,
                        current_wp,
                        coord_frame,
                        command,
                        param1,
                        param2,
                        param3,
                        param4,
                        latitude,
                        longitude,
                        altitude,
                        autocontinue,
                    ) + "\n"
                )
            file.write(
                get_string_of_tab_separated_values(
                    len(waypoints),
                    0,
                    3,
                    20,
                    0,
                    0,
                    0,
                    0,
                    waypoints[-1][1],
                    waypoints[-1][0],
                    45,
                    1
                )
            )

    def processAlgorithm(self, parameters, context: QgsProcessingContext, feedback): 
        """
        Ejecuta el flujo principal del algoritmo de procesamiento.

        Este método es invocado automáticamente por QGIS cuando el usuario
        ejecuta el algoritmo desde la interfaz. Coordina todas las operaciones
        necesarias para transformar una capa de polígonos en datos útiles
        para navegación de dron (vértices, waypoints y plan de misión).

        Parameters
        ----------
        parameters : dict
            Diccionario con los parámetros de entrada definidos en initAlgorithm.
            Contiene la capa de polígonos y la ruta del archivo de salida.
        
        context : QgsProcessingContext
            Contexto de ejecución del algoritmo dentro de QGIS.
        
        feedback : QgsProcessingFeedback
            Objeto para reportar progreso, mensajes o errores durante la ejecución.

        Returns
        -------
        dict
            Diccionario con la ruta del archivo CSV generado.

        Flujo general
        -------------
        1. Obtiene la capa de polígonos de entrada y el sistema de referencia espacial (CRS).
        2. Obtiene la ruta del archivo CSV de salida.
        3. Valida que la capa de entrada exista.
        4. Extrae los vértices del polígono como una nueva capa.
        5. Añade campos adicionales (lon, lat, alt, orden).
        6. Asigna valores a cada vértice (coordenadas y orden).
        7. Exporta los vértices a un archivo CSV.
        8. Corrige la ruta del archivo CSV si es necesario.
        9. Filtra el CSV para conservar únicamente los campos relevantes.
        10. Añade el CSV como capa en el proyecto QGIS.
        11. Genera waypoints a partir del polígono.
        12. Exporta los waypoints a un nuevo CSV y lo añade al proyecto.
        13. Crea capas visuales en QGIS (puntos y línea de ruta).
        14. Genera un archivo de plan de misión para dron.

        Métodos utilizados
        ------------------
        - self.parameterAsSource()
        - self.parameterAsFileOutput()
        - self.extract_vertices()
        - self.add_fields()
        - self.assign_vertex_attributes()
        - self.export_to_csv()
        - self.resolve_csv_path()
        - self.filter_csv_fields()
        - self.add_csv_layer_to_project()
        - self.generate_waypoints()
        - self.add_waypoints_to_qgis()
        - self.write_mission_plan()

        Notas
        -----
        - Este método actúa como orquestador del algoritmo.
        - Depende de múltiples funciones auxiliares para dividir la lógica
        en pasos claros y reutilizables.
        - El resultado final no solo es un CSV, sino también capas visuales
        y un archivo de misión compatible con sistemas de drones.
        """
        polygon = self.parameterAsSource(parameters, self.POLYGON, context)
        crs = polygon.sourceCrs()
        output_csv = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        if polygon is None:
            raise QgsProcessingException("No se pudo obtener la capa de entrada.")

        vertices = self.extract_vertices(parameters[self.POLYGON], context)
        self.add_fields(vertices)
        self.assign_vertex_attributes(vertices)
        self.export_to_csv(vertices, output_csv)
        output_csv = self.resolve_csv_path(output_csv)

        fields = ["lon", "lat", "alt", "orden"]
        self.filter_csv_fields(output_csv, fields)

        base_name = os.path.splitext(os.path.basename(output_csv))[0]

        self.add_csv_layer_to_project(output_csv, base_name + "_points")

        waypoints, waypoints_csv = self.generate_waypoints(output_csv)
        self.add_csv_layer_to_project(waypoints_csv, base_name + "_waypoints")

        self.add_waypoints_to_qgis(waypoints, crs, base_name)

        self.write_mission_plan(waypoints, output_csv)

        return {self.OUTPUT: output_csv}

    def name(self):
        return 'exportar_vertices_dron'

    def displayName(self):
        return 'Exportar vértices para dron (CSV)'

    def group(self):
        return 'Herramientas personalizadas'

    def groupId(self):
        return 'herramientas_personalizadas'

    def createInstance(self):
        """
        Crea y retorna una nueva instancia del algoritmo de procesamiento.

        Este método es requerido por la API de procesamiento de QGIS para permitir
        que el algoritmo sea instanciado correctamente cada vez que se ejecuta.
        QGIS lo utiliza internamente para generar una nueva instancia independiente,
        evitando conflictos entre múltiples ejecuciones.

        Returns
        -------
        ExportVertices
            Nueva instancia de la clase ExportVertices.
        """
        return ExportVertices()

# Código de generación de waypoints a partir de un polígono

class SweepingSegment: 
    def __init__(self, latitude): 
        self.latitude = latitude
        self.segment = shapely.LineString([(-180, latitude), (180, latitude)])
        self.LATITUDE_DECREMENT_PER_LEVEL = 0.000045 # ~ 5 metros

    def sweep(self): 
        self.latitude -= self.LATITUDE_DECREMENT_PER_LEVEL
        self.segment = shapely.LineString([(-180, self.latitude), (180, self.latitude)])

    def intersection(self, segment): 
        return shapely.intersection(self.segment, segment)

def read_points(polygon_file_path): 
    import csv
    with open(polygon_file_path, 'r') as file:
        csv_reader = csv.reader(file)
        points = []
        for x, y, _, __ in csv_reader:
            is_not_first_row = x != 'lon'
            if is_not_first_row:
                points.append((float(x), float(y)))
        return points
    return None

def get_waypoints_from_polygon(polygon_file_path): 

    # documentar con '''
    points = read_points(polygon_file_path)
    
    sweeping_segment_latitude = 0
    for point in points:
        sweeping_segment_latitude = max(sweeping_segment_latitude, point[1])
    sweeping_segment = SweepingSegment(sweeping_segment_latitude)

    waypoints_by_level = []
    while True:
        current_level = []
        for i in range(len(points)):
            polygon_segment = shapely.LineString([points[i], points[(i + 1) % len(points)]])
            inter = sweeping_segment.intersection(polygon_segment)
            current_level.extend(shapely.get_coordinates(inter).tolist())

        if not current_level:
            break

        current_level.sort()
        if len(waypoints_by_level) % 2 == 0:
            current_level.reverse()
        waypoints_by_level.append(current_level)

        sweeping_segment.sweep()

    waypoints = reduce(operator.concat, waypoints_by_level, [])
    
    seen = set()
    unique_waypoints = []
    for wp in waypoints:
        rounded_wp = (round(wp[0], COORDINATE_PRECISION), round(wp[1], COORDINATE_PRECISION))
        if rounded_wp not in seen:
            seen.add(rounded_wp)
            unique_waypoints.append(wp)
    return unique_waypoints

def write_waypoints_on_csv(waypoints, waypoints_file_path):
    import csv
    with open(waypoints_file_path, 'w', newline='') as file:
        csv_writer = csv.writer(file)
        csv_writer.writerow(['lon','lat','alt','orden'])
        for i in range(len(waypoints)):
            lon, lat = waypoints[i]
            csv_writer.writerow([round(lon, COORDINATE_PRECISION), round(lat, COORDINATE_PRECISION), 20, i])
