import io
import json
import logging
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from src import (
    HealthResponse,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
    log_requests,
    setup_logging,
)
from src.storage import MOVIE_COLUMNS

from data_pipeline import (
    create_cleaning_report, 
    process_data, 
    validate_dataframe
)

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Movie API", version="1.0.0")
app.middleware("http")(log_requests)
storage = MovieStorage()

@app.get("/health", response_model=HealthResponse)
def health_check():
    """Return the application status and version."""
    return HealthResponse(status="ok", version=app.version)


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Validate a movie CSV and replace the stored collection."""
    # TODO 1: extension check, read, parse
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".csv":
        logger.warning(f"Unsupported file format: {suffix or "(none)"}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{suffix or '(none)'}'. Please upload a .csv file.",
        )

    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
    except pd.errors.EmptyDataError:
        logger.warning(f"Empty CSV upload: {file.filename}")
        raise HTTPException(status_code=400, detail="The uploaded CSV file is empty.")
    except (pd.errors.ParserError, UnicodeDecodeError) as error:
        logger.warning(f"Could not parse CSV: {file.filename}")
        raise HTTPException(
            status_code=400, detail="Could not parse the uploaded CSV file."
        ) from error

    # TODO 2: quick validation
    column_names = [str(col) for col in df.columns]
    if sorted(column_names) != sorted(MOVIE_COLUMNS):
        logger.warning(f"Invalid movie columns: {column_names}")
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have exactly these columns: {MOVIE_COLUMNS}",
        )
    if df.empty:
        logger.warning(f"CSV has no data rows: {file.filename}")
        raise HTTPException(status_code=400, detail="The CSV has no data rows.")

    df = df[MOVIE_COLUMNS]

    # TODO 3: save and return
    storage.save(df)
    logger.info(f"Uploaded movies: filename={file.filename}, rows={len(df)}")

    return {
        "filename": file.filename,
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": list(df.columns),
    }


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    """Return up to limit stored movies plus the total count."""
    data = storage.select_columns(MOVIE_COLUMNS, limit=limit)
    total_rows = storage.count_movies()
    response = {"data": data, "total_rows": total_rows}
    logger.info(f"Retrieved movies: returned_rows={len(data)}")
    return response

@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Filter movies by minimum rating using SQL."""
    try:
        results = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    logger.info(
        "Queried movies: columns=%s, min_rating=%s, returned_rows=%d",
        columns, min_rating, len(results),
    )
    return results

@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and process the stored movies using MP1 functions."""
    # TODO 1: retrieve
    df = storage.get()
    if df.empty:
        logger.warning("No movies stored to process")
        raise HTTPException(
            status_code=400, detail="No movies stored. Upload a CSV first."
        )

    # TODO 2: reuse MP2 logic
    config_dict = config.model_dump()
    required_columns = config_dict["validation"]["required_columns"]
    numeric_columns = config_dict["validation"]["numeric_columns"]

    missing_numeric = [col for col in numeric_columns if col not in df.columns]
    if missing_numeric:
        logger.warning(f"Numeric columns not found: {missing_numeric}")
        raise HTTPException(
            status_code=400,
            detail=f"Numeric columns not found in dataset: {missing_numeric}",
        )

    try:
        validated = validate_dataframe(df, required_columns, numeric_columns)
        validation_removed = len(df) - len(validated)
        logger.info(f"Validated movies: {len(df)} -> {len(validated)} rows")

        original = validated.copy()
        processed = process_data(validated, config_dict)
    except ValueError as error:
        logger.warning(f"Processing failed: error={error}")
        raise HTTPException(status_code=400, detail=str(error)) from error

    report = create_cleaning_report(original, processed)

    # TODO 3: save and return
    storage.save(processed)
    logger.info(
        f"Processed movies: validation_removed={validation_removed}, rows_before={report["rows_before"]}, rows_after={report["rows_after"]}"
    )

    return {
        "validation_rows_removed": validation_removed,
        "cleaning_report": report,
    }
