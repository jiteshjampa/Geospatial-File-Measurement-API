# FieldScope — Geospatial File Measurement API

A FastAPI service and small map-based web interface for uploading zipped Shapefiles and KML survey files. It extracts feature geometry and attributes, converts geometries to WGS84 for map display, and calculates polygon area or line length in a locally selected projected CRS.

## What it does

1. Accepts a `.kml` file or a `.zip` containing exactly one Shapefile (`.shp`, `.dbf`, and `.prj`; `.shx` is optional).
2. Reads every feature's geometry and attributes. KML input is treated as EPSG:4326; Shapefiles must include a valid `.prj` file.
3. Transforms geometries into EPSG:4326 for consistent API output and interactive map display.
4. For each Polygon/MultiPolygon or LineString/MultiLineString, chooses a local projected CRS and calculates area in square meters or length in meters. Point features are retained without a measurement. Invalid and unsupported geometries are returned with a status and explanation rather than aborting the whole upload.
5. Saves file metadata, properties, output geometries, and measurements in SQLite so the GET endpoints continue to work after the request finishes.

The UI is served at `/` and the interactive OpenAPI documentation is at `/docs`.
Ready-to-upload examples are in `sample_data/`: `sample_survey.kml` contains a polygon, line, and point; `sample_survey.zip` contains a small polygon Shapefile.

## Requirements and local setup (Windows PowerShell)

Install Python 3.11 or newer. From this project folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) for the map UI or [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to try the API. The default database is `aereo.db` in the project folder. Configuration can also be set as environment variables; see `.env.example`. The application does not automatically load `.env`, so export a variable in PowerShell before starting the server when you need a non-default setting:

```powershell
$env:DATABASE_URL = "sqlite:///./aereo.db"
$env:MAX_UPLOAD_MB = "50"
uvicorn app.main:app --reload
```

Run the tests:

```powershell
pytest -q
```

### Docker

Build and run the API/UI container:

```powershell
docker build -t fieldscope .
docker run --rm -p 8000:8000 -e DATABASE_URL=sqlite:////data/aereo.db -v fieldscope-data:/data fieldscope
```

For a real deployment, configure a persistent database volume or an external database, and review storage, backups, authentication, and upload limits for your environment.

## API

All uploads use multipart form data with a field named `file`.

### `POST /api/files/`

Upload and process a KML or zipped Shapefile:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/files/" -F "file=@C:\data\survey.kml"
```

Example `201 Created` response:

```json
{
  "id": "3f8e4e0a-a283-4d50-a93f-917ab729b6f6",
  "filename": "survey.kml",
  "feature_count": 2,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "created_at": "2026-10-07T10:00:00"
}
```

Example zipped Shapefile upload:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/files/" -F "file=@C:\data\survey.zip"
```

### `GET /api/files/{id}/`

Return stored upload metadata and processing status. Returns `404` if the ID does not exist.

### `GET /api/files/{id}/measurements/`

Return every feature's index, geometry type, output geometry, geometry CRS, source properties, measurement fields, status, and explanatory message. Geometry coordinates in this response are EPSG:4326. `area_m2` is set for supported polygon features; `length_m` is set for supported line features; the other measurement field is `null`.

Example feature:

```json
{
  "feature_index": 0,
  "geometry_type": "Polygon",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[12.0, 55.0], [12.01, 55.0], [12.01, 55.01], [12.0, 55.0]]]
  },
  "geometry_crs": "EPSG:4326",
  "properties": {"site": "north"},
  "area_m2": 710000.0,
  "length_m": null,
  "measurement_status": "measured",
  "message": null
}
```

### `GET /api/files/{id}/features/?offset=0&limit=100`

Return a page of feature records. `offset` must be nonnegative; `limit` is 1–1000. This is useful for clients that do not need the full measurement response at once.

### `GET /health`

Lightweight health check; returns `{"status":"ok"}`.

Uploads larger than `MAX_UPLOAD_MB` are rejected with `413`. Invalid file formats, malformed archives, missing Shapefile CRS metadata, and invalid KML return `422` with a useful detail message.

## Architecture

```text
app/
  api.py                 FastAPI upload, metadata, measurement, and feature-page endpoints
  core/config.py         Upload limits and database configuration
  db.py                  SQLAlchemy engine, session, and declarative base
  models.py              UploadedFile and MeasuredFeature persistence models
  schemas.py             Typed API response contracts
  services/geospatial.py KML/ZIP parsing, CRS transforms, and measurement calculations
  static/                Map UI (Leaflet), styles, and browser-side upload flow
tests/                   Geospatial calculation and HTTP API tests
```

The request handler validates the filename and upload size, the parsing service produces a dataset with its source CRS, and each feature is measured independently. A successful upload and all its feature results are committed in one database transaction. The response geometry is kept in WGS84 so web maps can render it directly; its CRS is explicitly returned. Original upload bytes are processed in memory and are not retained.

## CRS and measurement strategy

Area and length are never calculated from longitude/latitude degrees. Every geometry is first transformed from its source CRS to EPSG:4326. A local UTM zone is selected from the geometry centroid for normal latitudes; polar stereographic EPSG:3413 (north) or EPSG:3031 (south) is used above/below the UTM latitude range. The geometry is projected to that CRS before Shapely calculates area and length. Coordinates in these projected systems use meters.

This is a practical local-survey strategy, not a substitute for a domain-specific geodetic or legal-survey workflow. UTM distortion increases for very large features spanning multiple zones. Such use cases should select a projection based on an explicitly defined area of interest or use geodesic calculations as appropriate.

## Design decisions and trade-offs

- **FastAPI:** provides typed request/response contracts, automatic OpenAPI docs, and straightforward async file upload. The processing and SQLite work are synchronous and suitable for this small assignment; high-volume processing would move to a worker queue.
- **pyshp, Shapely, and pyproj:** pyshp reads zipped Shapefiles without a native GDAL installation; Shapely handles geometry operations, and pyproj handles CRS identification and transformations.
- **KML parser:** the XML parser supports Point, LineString, Polygon, homogeneous multi-geometries, and basic name/description/ExtendedData properties. KML is defined in EPSG:4326.
- **SQLite + SQLAlchemy:** zero-service local persistence keeps the demo easy to run. PostgreSQL/PostGIS is the natural production choice for larger geospatial datasets and spatial queries.
- **Response geometry:** returned as WGS84 GeoJSON-style geometry for browser mapping; measurements are computed in a separate projected CRS. Each feature has an explicit measurement status so a point, malformed geometry, or unsupported collection does not fail the entire dataset.
- **Limits and input safety:** upload and expanded-archive sizes, archive entry count, feature count, unsafe XML declarations, and unsupported file types are checked. The API has no authentication and is intended as a local assignment/demo, not a public multi-user deployment.
- **Map libraries and tiles:** Leaflet and OpenStreetMap tiles are loaded by the browser from their public CDNs/services; an internet connection is required for the basemap. The API itself does not send uploaded survey data to a third party.

## Learning and future scope

This project demonstrates REST API design, Python type annotations, file validation, geospatial file parsing, projected CRS selection, SQL persistence, pagination, automated tests, and a browser client.

Possible next steps: add authentication and per-user file ownership, background jobs for large uploads, Postgres/PostGIS, support more formats and richer KML schemas, store original uploads in object storage, add export/download and spatial filters, and add deployment observability and rate limiting.

