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
        return processing.run("native:extractvertices", {
            'INPUT': polygon,
            'OUTPUT': 'memory:vertices'
        }, context=context)['OUTPUT']

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
                    lon_idx: round(pt.x(), COORDINATE_PRECISION),
                    lat_idx: round(pt.y(), COORDINATE_PRECISION),
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
