"""FastAPI web service for scraping reviews from Google Maps and TripAdvisor."""
import csv
import io
from enum import Enum

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from scraper.gmap import scrape_gmap_reviews
from scraper.tripadvisor import scrape_tripadvisor_reviews

app = FastAPI(title="Review Scraper API")


class Source(str, Enum):
    gmap = "gmap"
    tripadvisor = "tripadvisor"


class ScrapeRequest(BaseModel):
    url: str
    source: Source


@app.post("/scrape")
def scrape(req: ScrapeRequest, format: str = Query(default="json")):
    """Scrape reviews from the given URL.

    Returns JSON by default, or CSV with ?format=csv.
    """
    try:
        if req.source == Source.gmap:
            reviews = scrape_gmap_reviews(req.url)
        else:
            reviews = scrape_tripadvisor_reviews(req.url)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)
    except RuntimeError as e:
        return JSONResponse(content={"error": str(e)}, status_code=503)

    if format == "csv":
        return _csv_response(reviews)

    return JSONResponse(content=reviews)


def _csv_response(reviews: list[dict]) -> StreamingResponse:
    """Build a CSV streaming response from reviews."""
    output = io.StringIO()
    # Write BOM for Excel compatibility
    output.write("\ufeff")
    writer = csv.DictWriter(
        output,
        fieldnames=["review_id", "author", "rating", "date", "comment"],
    )
    writer.writeheader()
    writer.writerows(reviews)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=reviews.csv"},
    )
