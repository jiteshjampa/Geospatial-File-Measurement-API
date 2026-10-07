import io
import zipfile

import pytest
import shapefile
from pyproj import CRS
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.services.geospatial import (
    InvalidGeospatialFile,
    ParsedFeature,
    _parse_kml,
    _parse_shapefile_zip,
    parse_upload,
    process_feature,
)


def test_polygon_area_uses_projected_meters():
    polygon = Polygon([
        (12.0, 55.0), (12.01, 55.0), (12.01, 55.01), (12.0, 55.01), (12.0, 55.0)
    ])
    result = process_feature(ParsedFeature(polygon, {"site": "north"}), CRS.from_epsg(4326))
    assert result.measurement_status == "measured"
    assert result.area_m2 == pytest.approx(710_000, rel=0.08)
    assert result.length_m is None
    assert result.geometry["type"] == "Polygon"


def test_line_length_uses_projected_meters():
    line = LineString([(0, 0), (0.01, 0)])
    result = process_feature(ParsedFeature(line, {}), CRS.from_epsg(4326))
    assert result.length_m == pytest.approx(1_113, rel=0.02)
    assert result.area_m2 is None


def test_point_is_supported_without_measurement():
    result = process_feature(ParsedFeature(Point(12, 55), {}), CRS.from_epsg(4326))
    assert result.measurement_status == "not_applicable"
    assert result.area_m2 is None
    assert result.length_m is None


def test_unsupported_geometry_is_reported_without_crashing():
    result = process_feature(
        ParsedFeature(GeometryCollection([Point(12, 55)]), {}), CRS.from_epsg(4326)
    )
    assert result.measurement_status == "unsupported"


def test_kml_extracts_geometry_and_properties():
    data = b"""<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark>
      <name>Plot A</name><ExtendedData><Data name="owner"><value>Survey team</value></Data></ExtendedData>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
      12,55 12.01,55 12.01,55.01 12,55.01 12,55
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark></kml>"""
    dataset = _parse_kml(data)
    assert dataset.crs.to_epsg() == 4326
    assert len(dataset.features) == 1
    assert dataset.features[0].geometry.geom_type == "Polygon"
    assert dataset.features[0].properties == {"name": "Plot A", "owner": "Survey team"}


def test_kml_rejects_entity_declarations():
    with pytest.raises(InvalidGeospatialFile, match="DTD or entity"):
        _parse_kml(b'<!DOCTYPE x [<!ENTITY y "z">]><kml/>')


def test_zip_shapefile_requires_projection_file():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("survey/survey.shp", b"not a shapefile")
        archive.writestr("survey/survey.dbf", b"not a dbf")
    with pytest.raises(InvalidGeospatialFile, match=".prj"):
        _parse_shapefile_zip(data.getvalue(), 1024 * 1024)


def test_zip_shapefile_reads_geometry_properties_and_crs():
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    writer.field("site", "C")
    writer.poly([[
        (12.0, 55.0), (12.001, 55.0), (12.001, 55.001),
        (12.0, 55.001), (12.0, 55.0),
    ]])
    writer.record("north")
    writer.close()
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("survey.shp", shp.getvalue())
        archive.writestr("survey.shx", shx.getvalue())
        archive.writestr("survey.dbf", dbf.getvalue())
        archive.writestr("survey.prj", CRS.from_epsg(4326).to_wkt())

    dataset = _parse_shapefile_zip(data.getvalue(), 1024 * 1024)
    assert dataset.crs.to_epsg() == 4326
    assert len(dataset.features) == 1
    assert dataset.features[0].geometry.geom_type == "Polygon"
    assert dataset.features[0].properties == {"site": "north"}
    result = process_feature(dataset.features[0], dataset.crs)
    assert result.measurement_status == "measured"
    assert result.area_m2 > 0


def test_upload_rejects_unknown_extension():
    with pytest.raises(InvalidGeospatialFile, match="Only .kml"):
        parse_upload("survey.geojson", b"{}", 1024)
