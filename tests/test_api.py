import io

from fastapi.testclient import TestClient
from app.db import make_engine
from app.main import create_app


def make_test_client():
    engine = make_engine("sqlite:///:memory:")
    return TestClient(create_app(engine))


def test_kml_upload_details_measurements_and_pagination():
    kml = b"""<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark>
      <name>Test plot</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
      12,55 12.001,55 12.001,55.001 12,55.001 12,55
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark></kml>"""
    with make_test_client() as client:
        upload = client.post(
            "/api/files/",
            files={"file": ("plot.kml", io.BytesIO(kml), "application/vnd.google-earth.kml+xml")},
        )
        assert upload.status_code == 201
        file_data = upload.json()
        assert file_data["feature_count"] == 1
        assert file_data["crs"] == "EPSG:4326"

        details = client.get(f"/api/files/{file_data['id']}/")
        assert details.status_code == 200
        assert details.json()["status"] == "COMPLETED"

        measurements = client.get(f"/api/files/{file_data['id']}/measurements/")
        assert measurements.status_code == 200
        feature = measurements.json()["features"][0]
        assert feature["geometry_crs"] == "EPSG:4326"
        assert feature["measurement_status"] == "measured"
        assert feature["area_m2"] > 0
        assert feature["properties"]["name"] == "Test plot"

        page = client.get(f"/api/files/{file_data['id']}/features/?offset=0&limit=1")
        assert page.status_code == 200
        assert page.json()["total"] == 1


def test_upload_validation_and_missing_file_response():
    with make_test_client() as client:
        bad_upload = client.post("/api/files/", files={"file": ("data.txt", b"hello")})
        assert bad_upload.status_code == 422
        assert client.get("/api/files/not-a-file/").status_code == 404
        assert client.get("/health").json() == {"status": "ok"}
        assert "FieldScope" in client.get("/").text
        assert client.get("/static/app.js").status_code == 200
