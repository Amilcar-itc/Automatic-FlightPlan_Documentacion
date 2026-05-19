"""
Script de procesamiento para exportar puntos a un archivo CSV con coordenadas 
lat/lon redondeadas y generar plan de misión para drones.
"""

from math import sqrt
import os
import csv

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QFont, QColor
from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsWkbTypes,
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
    QgsProcessingException,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsTextBufferSettings
)


class ExportVertices(QgsProcessingAlgorithm):
    POINTS = 'POINTS'
    OUTPUT = 'OUTPUT'
    COORDINATE_PRECISION = 8

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.POINTS,
                'Capa de puntos',
                [QgsProcessing.TypeVectorPoint]
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                'Archivo CSV de salida',
                fileFilter='CSV (*.csv)'
            )
        )

    def add_fields(self, layer):
        layer.dataProvider().addAttributes([
            QgsField("lon", QVariant.Double),
            QgsField("lat", QVariant.Double),
            QgsField("alt", QVariant.Double),
            QgsField("orden", QVariant.Int)
        ])
        layer.updateFields()


    def assign_vertex_attributes(self, layer):
        lon_idx = layer.fields().indexFromName("lon")
        lat_idx = layer.fields().indexFromName("lat")
        alt_idx = layer.fields().indexFromName("alt")
        orden_idx = layer.fields().indexFromName("orden")
        for i, feat in enumerate(layer.getFeatures()):
            pt = feat.geometry().asPoint()
            layer.dataProvider().changeAttributeValues({
                feat.id(): {
                    lon_idx: round(pt.x(), self.COORDINATE_PRECISION),
                    lat_idx: round(pt.y(), self.COORDINATE_PRECISION),
                    alt_idx: 20.0,
                    orden_idx: i
                }
            })

    def export_to_csv(self, layer, output_csv):
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
        if not os.path.exists(output_csv):
            base, ext = os.path.splitext(output_csv)
            if ext.lower() != ".csv" and os.path.exists(base + ".csv"):
                return base + ".csv"
        return output_csv

    def filter_csv_fields(self, output_csv, fields):
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
        csv_layer = QgsVectorLayer(
            path=csv_path,
            baseName=layer_name,
            providerLib="ogr"
        )
        if csv_layer.isValid():
            QgsProject.instance().addMapLayer(csv_layer)

    def write_waypoints_on_csv(self, waypoints, waypoints_file_path):
        """Escribe waypoints en archivo CSV"""
        with open(waypoints_file_path, 'w', newline='', encoding='utf-8') as file:
            csv_writer = csv.writer(file)
            csv_writer.writerow(['lon', 'lat', 'alt', 'orden'])
            for i, (lon, lat) in enumerate(waypoints):
                csv_writer.writerow([
                    round(lon, self.COORDINATE_PRECISION), 
                    round(lat, self.COORDINATE_PRECISION), 
                    20, 
                    i
                ])

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
        
    def optimize_route(self, points):
        """Optimiza la ruta de puntos usando algoritmo greedy del vecino más cercano"""
        if not points:
            return []
        
        # Encontrar punto inicial (lo más cercano a una esquina)
        edge_point = points[0]
        for point in points:
            if abs(point[0]) < abs(edge_point[0]) or abs(point[1]) < abs(edge_point[1]):
                edge_point = point

        optimized_route = [edge_point]
        unvisited_points = [p for p in points if p != edge_point]

        while unvisited_points:
            min_distance = float('inf')
            next_point = None
            
            for point in unvisited_points:
                distance = sqrt(
                    pow(point[0] - edge_point[0], 2) +
                    pow(point[1] - edge_point[1], 2)
                )

                if distance < min_distance:
                    min_distance = distance
                    next_point = point

            if next_point:
                optimized_route.append(next_point)
                unvisited_points.remove(next_point)
                edge_point = next_point

            else:
                break

        return optimized_route



    def processAlgorithm(self, parameters, context: QgsProcessingContext, feedback):
        input_points = self.parameterAsSource(parameters, self.POINTS, context)
        output_csv = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        if input_points is None:
            raise QgsProcessingException("No se pudo obtener la capa de entrada.")

        # Transformar puntos a WGS84 (EPSG:4326)
        original_crs = input_points.sourceCrs()
        new_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform_crs = QgsCoordinateTransform(original_crs, new_crs, QgsProject.instance())

        points_wgs = []

        # Extraer y transformar todos los puntos a WGS84
        for feature in input_points.getFeatures():
            geom = feature.geometry()
            if geom.type() != QgsWkbTypes.PointGeometry:
                continue

            point = geom.asPoint()
            wgs_point = transform_crs.transform(point)

            lon = round(wgs_point.x(), self.COORDINATE_PRECISION)
            lat = round(wgs_point.y(), self.COORDINATE_PRECISION)
            points_wgs.append((lon, lat))

        if not points_wgs:
            raise QgsProcessingException("La capa de entrada no contiene puntos válidos.")

        # Optimizar ruta de waypoints
        waypoints = self.optimize_route(points_wgs)

        # waypoints en CSV
        self.write_waypoints_on_csv(waypoints, output_csv)

        # Filtrar campos del CSV
        fields = ["lon", "lat", "alt", "orden"]
        self.filter_csv_fields(output_csv, fields)

        base_name = os.path.splitext(os.path.basename(output_csv))[0]

        # Agregar CSV a proyecto
        self.add_csv_layer_to_project(output_csv, base_name + "_waypoints")

        # Agregar capa de waypoints en QGIS
        self.add_waypoints_to_qgis(waypoints, new_crs, base_name)

        # Generar plan de vuelo
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
        return ExportVertices()

