# MP3: Movie API with SQLite and Caching

This project is a FastAPI application that stores a single movie collection in a SQLite database and serves it through a REST API. `POST /upload` checks that a CSV has exactly the columns `title`, `release_year`, `rating`, and `genre`, then replaces the stored collection in one transaction. The `src/database.py` module creates connections and the `movies` table, while `src/storage.py` (`MovieStorage`) saves, retrieves, counts, and filters movies using SQL. `GET /movies` returns stored movies with a total count, and `GET /movies/search` filters by minimum rating and returns only the requested columns, sorted by rating. `POST /movies/process` reuses the MP1 pipeline in `data_pipeline/` to validate and clean the collection, then saves the cleaned rows back to SQLite. Responses from `GET /movies` are cached per limit in FakeRedis (`src/cache.py`) for 90 seconds, and the cache is cleared after every successful upload or processing run so clients never see outdated data. Because the data lives in SQLite, it persists across server restarts, while request logging middleware (`src/middleware.py`) records each request with a unique ID.

## Run the API

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Then open http://127.0.0.1:8000/docs.

## Run the tests

```bash
python -m pytest tests -v
```

## Sample processing request

After uploading `fixtures/sample_movies.csv`, send `POST /movies/process` with:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {
      "enabled": true,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

Expected result:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20,
    "rows_after": 16,
    "rows_removed": 4,
    "columns_before": 4,
    "columns_after": 4,
    "columns_removed": 0
  }
}
```

Afterward, `GET /movies?limit=100` returns `total_rows: 16`.