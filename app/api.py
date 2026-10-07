from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_max_archive_bytes, get_max_upload_bytes
from app.db import get_db
from app.models import MeasuredFeature, UploadedFile
from app.schemas import FeatureMeasurement, FeaturePage, FileSummary, MeasurementsResponse
from app.services.geospatial import InvalidGeospatialFile, parse_upload, process_feature

router = APIRouter(prefix="/api", tags=["geospatial files"])


@router.post("/files/", response_model=FileSummary, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadedFile:
    filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or len(filename) > 255:
        raise HTTPException(status_code=422, detail="Provide a valid filename of at most 255 characters.")

    limit = get_max_upload_bytes()
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds the {limit // (1024 * 1024)} MB file-size limit.",
        )
    try:
        dataset = parse_upload(filename, content, get_max_archive_bytes())
        processed = [process_feature(feature, dataset.crs) for feature in dataset.features]
    except InvalidGeospatialFile as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stored_file = UploadedFile(
        id=str(uuid4()),
        filename=filename,
        feature_count=len(processed),
        crs=dataset.crs.to_string(),
        status="COMPLETED",
        features=[
            MeasuredFeature(
                feature_index=index,
                geometry_type=feature.geometry_type,
                geometry=feature.geometry,
                geometry_crs="EPSG:4326",
                properties=feature.properties,
                area_m2=feature.area_m2,
                length_m=feature.length_m,
                measurement_status=feature.measurement_status,
                message=feature.message,
            )
            for index, feature in enumerate(processed)
        ],
    )
    db.add(stored_file)
    db.commit()
    db.refresh(stored_file)
    return stored_file


def _get_file(file_id: str, db: Session) -> UploadedFile:
    stored_file = db.get(UploadedFile, file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Uploaded file not found.")
    return stored_file


def _feature_response(feature: MeasuredFeature) -> FeatureMeasurement:
    return FeatureMeasurement(
        feature_index=feature.feature_index,
        geometry_type=feature.geometry_type,
        geometry=feature.geometry,
        geometry_crs=feature.geometry_crs,
        properties=feature.properties,
        area_m2=feature.area_m2,
        length_m=feature.length_m,
        measurement_status=feature.measurement_status,
        message=feature.message,
    )


@router.get("/files/{file_id}/", response_model=FileSummary)
def get_file(file_id: str, db: Session = Depends(get_db)) -> UploadedFile:
    return _get_file(file_id, db)


@router.get("/files/{file_id}/measurements/", response_model=MeasurementsResponse)
def get_measurements(file_id: str, db: Session = Depends(get_db)) -> MeasurementsResponse:
    stored_file = _get_file(file_id, db)
    features = db.scalars(
        select(MeasuredFeature)
        .where(MeasuredFeature.file_id == file_id)
        .order_by(MeasuredFeature.feature_index)
    ).all()
    return MeasurementsResponse(
        file_id=stored_file.id,
        filename=stored_file.filename,
        crs=stored_file.crs,
        feature_count=stored_file.feature_count,
        features=[_feature_response(feature) for feature in features],
    )


@router.get("/files/{file_id}/features/", response_model=FeaturePage)
def get_features(
    file_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> FeaturePage:
    stored_file = _get_file(file_id, db)
    features = db.scalars(
        select(MeasuredFeature)
        .where(MeasuredFeature.file_id == file_id)
        .order_by(MeasuredFeature.feature_index)
        .offset(offset)
        .limit(limit)
    ).all()
    return FeaturePage(
        file_id=stored_file.id,
        total=stored_file.feature_count,
        offset=offset,
        limit=limit,
        features=[_feature_response(feature) for feature in features],
    )
