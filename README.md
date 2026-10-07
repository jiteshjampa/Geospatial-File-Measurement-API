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

### Try the included sample

1. Start the application using the setup steps below.
2. Open [http://127.0.0.1:8000](http://127.0.0.1:8000).
3. Select `sample_data/sample_survey.kml` (or drag it onto the upload area) and choose **Process file**.
4. The page shows the uploaded file's source CRS and feature count, draws available geometries on the map, and lists area, length, and measurement status for each feature.

The KML sample includes a polygon, line, and point. Expect the polygon to have an area of roughly 12,000 m² and the line a length of roughly 167 m; exact results depend on the selected projection. The point appears on the map but has no area or length, as required by the assignment. You can also select `sample_data/sample_survey.zip` to check Shapefile uploads.

## Local installation explained

The app uses Python 3.11 or newer. Run these commands from the project directory in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- `venv` creates an isolated Python environment for this project; activating it makes its Python and installed packages available in the current PowerShell window.
- `pip install -r requirements.txt` installs the libraries listed in the project's dependency file.
- `uvicorn app.main:app --reload` starts the server. `app.main` points to `app/main.py`, `app` is the FastAPI application object in that module, and `--reload` restarts the server when Python files change.
- Open `/` for the upload and map interface or `/docs` for FastAPI's interactive API explorer.
- The first app startup creates a local SQLite database named `aereo.db` in the working directory. No database server installation is required.

The `.env.example` file documents configuration settings, but the application does not automatically load `.env`. Set environment variables in PowerShell before starting Uvicorn if you want to override defaults.

## Request lifecycle and code concepts

```text
Browser form (app/static/app.js)
    │ multipart/form-data: file
    ▼
FastAPI route (app/api.py)
    │ validates filename/size; receives a database session
    ▼
Geospatial service (app/services/geospatial.py)
    │ parses KML or zipped Shapefile; extracts features/properties/CRS
    │ transforms coordinates; calculates supported measurements
    ▼
SQLAlchemy models + SQLite (app/models.py, app/db.py)
    │ persists upload and its feature records
    ▼
JSON response → browser fetches measurements → Leaflet map + results table
```

FastAPI route decorators such as `@router.post(...)` and `@router.get(...)` map HTTP methods and paths to Python functions. They serve the same general purpose as Spring Boot's `@PostMapping`/`@GetMapping` or Express's `router.post`/`router.get`.

`Depends(get_db)` is FastAPI dependency injection. It asks FastAPI to call `get_db`, provide the route with a SQLAlchemy database session, and close the session after the request. `UploadFile = File(...)` declares a required multipart upload. `Query(default=0, ge=0)` declares a query parameter and validates that it is nonnegative. `async def` allows an endpoint to await asynchronous operations such as reading the uploaded file.

### Database models versus API schemas

- **SQLAlchemy models** in `app/models.py` describe database tables and relationships. `UploadedFile` represents one upload; `MeasuredFeature` represents one extracted feature. These define how application data is persisted.
- **Pydantic schemas** in `app/schemas.py` describe the API's validated input/output shapes. For example, `FileSummary` defines the JSON fields returned for a stored upload, and `MeasurementsResponse` defines the structure returned by the measurements endpoint.

In short: a **model** describes database persistence; a **schema** describes data crossing the API boundary. Keeping them separate lets the database have internal relationships while the API exposes a deliberate response format.

Python type annotations such as `str`, `int`, `float`, `list[FeatureMeasurement]`, and `dict | None` communicate expected value types. FastAPI and Pydantic use relevant annotations for request validation and response serialization. Ordinary Python type annotations alone do not enforce types at runtime.

### Database and persistence

The default database is **SQLite stored locally** in `aereo.db`; PostgreSQL is not configured in this project. SQLAlchemy is the Python ORM layer: it maps Python model classes to database tables and lets route/service code work with objects and queries instead of constructing SQL strings for each operation.

`app/db.py` creates the SQLAlchemy engine and session factory. `get_db` provides a short-lived session to API routes. `app/main.py` creates tables from the registered models at application startup. On upload, the route adds the upload and its related features, then commits them together. The uploaded source bytes are processed in memory and are not saved; extracted properties, WGS84 geometries, and measurement results are saved.

### What the geospatial libraries do

- **pyshp** (`shapefile`) reads the `.shp` geometry and `.dbf` attribute records from a ZIP without requiring a native GDAL installation.
- **Shapely** represents and validates points, lines, polygons, and collections; it also performs coordinate transformations and calculates projected area and length.
- **pyproj** reads the Shapefile `.prj` CRS and creates coordinate transformations between source, WGS84, and projected CRSs.
- Python's XML `ElementTree` parses KML placemarks, geometry, and basic properties.
- **Leaflet** draws uploaded features in the browser; OpenStreetMap tiles provide the basemap. The browser requires internet access for the CDN-hosted Leaflet assets and basemap tiles.

KML is treated as EPSG:4326. A Shapefile's CRS is read from its `.prj` file. Geometries are transformed to EPSG:4326 for map display, then polygons and lines are transformed to a local projected CRS before measurement. The API returns map geometries in EPSG:4326, polygon area in square meters (`area_m2`), and line length in meters (`length_m`).

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


Replace the remote URL with your repository URL. Run `pytest -q` and verify the README setup on a fresh environment before sharing the link.
