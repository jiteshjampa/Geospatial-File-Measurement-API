from __future__ import annotations

import io
import json
import math
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree

import shapefile
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError, ProjError
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, shape
from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform
from shapely.validation import explain_validity

WGS84 = CRS.from_epsg(4326)
MAX_FEATURES = 100_000
MAX_ARCHIVE_ENTRIES = 500


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class InvalidGeospatialFile(ValueError):
    """An upload is not a readable, supported geospatial file."""


def _read_archive_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> bytes:
    try:
        return archive.read(member)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise InvalidGeospatialFile("The ZIP archive contains a damaged file.") from exc


@dataclass(frozen=True)
class ParsedFeature:
    geometry: BaseGeometry | None
    properties: dict[str, Any]


@dataclass(frozen=True)
class ParsedDataset:
    crs: CRS
    features: list[ParsedFeature]


@dataclass(frozen=True)
class ProcessedFeature:
    geometry_type: str
    geometry: dict[str, Any] | None
    properties: dict[str, Any]
    area_m2: float | None
    length_m: float | None
    measurement_status: str
    message: str | None


def parse_upload(filename: str, content: bytes, max_archive_bytes: int) -> ParsedDataset:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "kml":
        return _parse_kml(content)
    if suffix == "zip":
        return _parse_shapefile_zip(content, max_archive_bytes)
    raise InvalidGeospatialFile("Only .kml files and .zip Shapefiles are supported.")


def _parse_shapefile_zip(content: bytes, max_archive_bytes: int) -> ParsedDataset:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise InvalidGeospatialFile("The uploaded .zip file is not a valid ZIP archive.") from exc

    with archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) > MAX_ARCHIVE_ENTRIES:
            raise InvalidGeospatialFile(
                f"The archive has too many entries; the limit is {MAX_ARCHIVE_ENTRIES}."
            )
        if sum(item.file_size for item in members) > max_archive_bytes:
            raise InvalidGeospatialFile("The uncompressed archive exceeds the configured size limit.")
        if any(item.file_size > 0 and item.compress_size == 0 for item in members):
            raise InvalidGeospatialFile("The archive contains an invalid compressed entry.")
        if any(
            item.file_size / max(item.compress_size, 1) > 1000
            for item in members
        ):
            raise InvalidGeospatialFile("The archive contains an unusually compressed entry.")

        shapefiles = [item for item in members if item.filename.lower().endswith(".shp")]
        if len(shapefiles) != 1:
            raise InvalidGeospatialFile("The ZIP archive must contain exactly one .shp file.")

        shp_member = shapefiles[0]
        shp_path = PurePosixPath(shp_member.filename.replace("\\", "/"))
        base = shp_path.with_suffix("").as_posix().lower()
        sibling_files = {
            PurePosixPath(item.filename.replace("\\", "/")).as_posix().lower(): item
            for item in members
        }
        dbf_member = sibling_files.get(base + ".dbf")
        shx_member = sibling_files.get(base + ".shx")
        prj_member = sibling_files.get(base + ".prj")
        if dbf_member is None:
            raise InvalidGeospatialFile("The Shapefile is missing its matching .dbf file.")
        if prj_member is None:
            raise InvalidGeospatialFile(
                "The Shapefile is missing its .prj coordinate-system file; its CRS is required."
            )
        try:
            projection_wkt = _read_archive_member(archive, prj_member).decode("utf-8-sig")
            source_crs = CRS.from_wkt(projection_wkt)
        except (UnicodeDecodeError, CRSError, ValueError, TypeError) as exc:
            raise InvalidGeospatialFile("The Shapefile .prj file contains an invalid CRS.") from exc

        shp_content = _read_archive_member(archive, shp_member)
        shx_content = _read_archive_member(archive, shx_member) if shx_member else None
        dbf_content = _read_archive_member(archive, dbf_member)
        for encoding in ("utf-8", "cp1252"):
            reader = None
            try:
                reader = shapefile.Reader(
                    shp=io.BytesIO(shp_content),
                    shx=io.BytesIO(shx_content) if shx_content else None,
                    dbf=io.BytesIO(dbf_content),
                    encoding=encoding,
                )
                fields = [field[0] for field in reader.fields[1:]]
                parsed: list[ParsedFeature] = []
                for index, record in enumerate(reader.iterShapeRecords()):
                    if index >= MAX_FEATURES:
                        raise InvalidGeospatialFile(f"Files are limited to {MAX_FEATURES} features.")
                    geometry = shape(record.shape.__geo_interface__) if record.shape.shapeType != shapefile.NULL else None
                    properties = _json_safe(dict(zip(fields, record.record)))
                    parsed.append(ParsedFeature(geometry, properties))
                return ParsedDataset(source_crs, parsed)
            except UnicodeDecodeError:
                if encoding == "cp1252":
                    raise InvalidGeospatialFile("The Shapefile attributes could not be decoded.")
            except InvalidGeospatialFile:
                raise
            except (shapefile.ShapefileException, ValueError, TypeError) as exc:
                raise InvalidGeospatialFile("The Shapefile geometry or attributes are malformed.") from exc
            finally:
                if reader is not None:
                    reader.close()
        raise InvalidGeospatialFile("The Shapefile attributes could not be decoded.")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_kml(content: bytes) -> ParsedDataset:
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise InvalidGeospatialFile("KML documents with DTD or entity declarations are not accepted.")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise InvalidGeospatialFile("The KML document is not valid XML.") from exc

    placemarks = [node for node in root.iter() if _local_name(node.tag) == "Placemark"]
    if len(placemarks) > MAX_FEATURES:
        raise InvalidGeospatialFile(f"Files are limited to {MAX_FEATURES} features.")
    parsed: list[ParsedFeature] = []
    for placemark in placemarks:
        properties: dict[str, Any] = {}
        geometries: list[BaseGeometry] = []
        for child in placemark:
            name = _local_name(child.tag)
            if name in {"name", "description"} and child.text:
                properties[name] = child.text.strip()
            elif name == "ExtendedData":
                for item in child.iter():
                    item_name = _local_name(item.tag)
                    if item_name in {"Data", "SimpleData"}:
                        key = item.attrib.get("name")
                        value_node = next(
                            (part for part in item if _local_name(part.tag) == "value"),
                            None,
                        )
                        value = value_node.text if value_node is not None else item.text
                        if key and value is not None:
                            properties[key] = value.strip()
            elif name in {"Point", "LineString", "Polygon", "MultiGeometry"}:
                geometries.append(_parse_kml_geometry(child))

        if not geometries:
            parsed.append(ParsedFeature(None, properties))
        elif len(geometries) == 1:
            parsed.append(ParsedFeature(geometries[0], properties))
        else:
            parsed.append(ParsedFeature(GeometryCollection(geometries), properties))
    return ParsedDataset(WGS84, parsed)


def _parse_kml_coordinates(node: ElementTree.Element) -> list[tuple[float, float]]:
    text = next(
        (part.text for part in node.iter() if _local_name(part.tag) == "coordinates"),
        None,
    )
    if not text:
        raise InvalidGeospatialFile("A KML geometry is missing its coordinates.")
    coordinates: list[tuple[float, float]] = []
    try:
        for coordinate in text.split():
            values = coordinate.split(",")
            if len(values) < 2:
                raise ValueError("A coordinate needs longitude and latitude.")
            longitude, latitude = float(values[0]), float(values[1])
            if not math.isfinite(longitude) or not math.isfinite(latitude):
                raise ValueError("Coordinates must be finite numbers.")
            coordinates.append((longitude, latitude))
    except ValueError as exc:
        raise InvalidGeospatialFile("A KML geometry contains invalid coordinates.") from exc
    return coordinates


def _parse_kml_geometry(node: ElementTree.Element) -> BaseGeometry:
    name = _local_name(node.tag)
    if name == "Point":
        coordinates = _parse_kml_coordinates(node)
        if len(coordinates) != 1:
            raise InvalidGeospatialFile("A KML point must contain exactly one coordinate.")
        return Point(coordinates[0])
    if name == "LineString":
        coordinates = _parse_kml_coordinates(node)
        if len(coordinates) < 2:
            raise InvalidGeospatialFile("A KML line must contain at least two coordinates.")
        return LineString(coordinates)
    if name == "Polygon":
        rings: list[list[tuple[float, float]]] = []
        for child in node:
            if _local_name(child.tag) in {"outerBoundaryIs", "innerBoundaryIs"}:
                rings.append(_parse_kml_coordinates(child))
        if not rings:
            raise InvalidGeospatialFile("A KML polygon is missing its boundary.")
        return Polygon(rings[0], rings[1:])
    if name == "MultiGeometry":
        children = [
            _parse_kml_geometry(child)
            for child in node
            if _local_name(child.tag) in {"Point", "LineString", "Polygon", "MultiGeometry"}
        ]
        if children and all(child.geom_type == "Polygon" for child in children):
            return MultiPolygon(children)
        if children and all(child.geom_type in {"LineString", "MultiLineString"} for child in children):
            lines = [
                line
                for child in children
                for line in (list(child.geoms) if child.geom_type == "MultiLineString" else [child])
            ]
            return MultiLineString(lines)
        if children and all(child.geom_type == "Point" for child in children):
            return MultiPoint(children)
        return GeometryCollection(children)
    raise InvalidGeospatialFile(f"Unsupported KML geometry element: {name}.")


def process_feature(feature: ParsedFeature, source_crs: CRS) -> ProcessedFeature:
    geometry = feature.geometry
    if geometry is None:
        return ProcessedFeature(
            "Unknown", None, feature.properties, None, None,
            "not_measured", "The feature has no geometry.",
        )
    geometry_type = geometry.geom_type
    try:
        to_wgs84 = Transformer.from_crs(source_crs, WGS84, always_xy=True).transform
        wgs84_geometry = transform(to_wgs84, geometry)
    except (ProjError, ValueError):
        return ProcessedFeature(
            geometry_type, None, feature.properties, None, None,
            "invalid_geometry", "The geometry could not be transformed to EPSG:4326.",
        )

    bounds = wgs84_geometry.bounds
    if (
        not bounds
        or not all(math.isfinite(value) for value in bounds)
        or bounds[0] < -180
        or bounds[2] > 180
        or bounds[1] < -90
        or bounds[3] > 90
    ):
        return ProcessedFeature(
            geometry_type, None, feature.properties, None, None,
            "invalid_geometry", "The geometry has coordinates outside valid longitude/latitude bounds.",
        )
    geometry_json = json.loads(json.dumps(wgs84_geometry.__geo_interface__))
    if not wgs84_geometry.is_valid:
        return ProcessedFeature(
            geometry_type, geometry_json, feature.properties, None, None,
            "invalid_geometry", explain_validity(wgs84_geometry),
        )
    if geometry_type == "Point":
        return ProcessedFeature(
            geometry_type, geometry_json, feature.properties, None, None,
            "not_applicable", "Point features do not have an area or length measurement.",
        )
    if geometry_type not in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
        return ProcessedFeature(
            geometry_type, geometry_json, feature.properties, None, None,
            "unsupported", "Measurements are supported for polygons and lines only.",
        )

    centroid = wgs84_geometry.centroid
    longitude, latitude = centroid.x, centroid.y
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return ProcessedFeature(
            geometry_type, geometry_json, feature.properties, None, None,
            "invalid_geometry", "The geometry centroid is outside valid longitude/latitude bounds.",
        )
    if latitude >= 84:
        projected_crs = CRS.from_epsg(3413)
    elif latitude <= -80:
        projected_crs = CRS.from_epsg(3031)
    else:
        zone = min(60, max(1, int((longitude + 180) // 6) + 1))
        projected_crs = CRS.from_epsg((32600 if latitude >= 0 else 32700) + zone)
    try:
        to_projected = Transformer.from_crs(WGS84, projected_crs, always_xy=True).transform
        projected_geometry = transform(to_projected, wgs84_geometry)
    except (ProjError, ValueError):
        return ProcessedFeature(
            geometry_type, geometry_json, feature.properties, None, None,
            "invalid_geometry", "The geometry could not be transformed for measurement.",
        )

    area_m2 = projected_geometry.area if geometry_type in {"Polygon", "MultiPolygon"} else None
    length_m = projected_geometry.length if geometry_type in {"LineString", "MultiLineString"} else None
    return ProcessedFeature(
        geometry_type, geometry_json, feature.properties, area_m2, length_m,
        "measured", None,
    )
