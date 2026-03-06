"""FastAPI web service for scraping reviews from Google Maps and TripAdvisor."""
import asyncio
import csv
import io
import uuid
from datetime import datetime, timezone
from enum import Enum

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel

from scraper.gmap import scrape_gmap_reviews
from scraper.tripadvisor import scrape_tripadvisor_reviews

app = FastAPI(title="Review Scraper API")

# In-memory job store (per-instance, lost on scale-to-zero)
jobs: dict[str, dict] = {}


class Source(str, Enum):
    gmap = "gmap"
    tripadvisor = "tripadvisor"


class ScrapeRequest(BaseModel):
    url: str
    source: Source


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/scrape")
async def scrape_async(req: ScrapeRequest):
    """Start a scraping job asynchronously. Returns job_id immediately."""
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "job_id": job_id,
        "url": req.url,
        "source": req.source.value,
        "status": "running",
        "progress": 0,
        "message": "開始中...",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reviews": [],
    }
    asyncio.create_task(_run_scrape(job_id, req.url, req.source))
    return JSONResponse(content={"job_id": job_id, "status": "running"}, status_code=202)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    """Get job status and results."""
    job = jobs.get(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    resp = {
        "job_id": job["job_id"],
        "url": job["url"],
        "source": job["source"],
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "created_at": job["created_at"],
        "review_count": len(job["reviews"]),
    }
    if job["status"] in ("done", "failed"):
        resp["reviews"] = job["reviews"]
        if job.get("error"):
            resp["error"] = job["error"]
    return JSONResponse(content=resp)


@app.get("/jobs/{job_id}/csv")
def get_job_csv(job_id: str):
    """Download job results as CSV."""
    job = jobs.get(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    if job["status"] != "done":
        return JSONResponse(content={"error": "Job not finished"}, status_code=400)
    return _csv_response(job["reviews"])


@app.get("/jobs")
def list_jobs():
    """List all jobs (summary only)."""
    return JSONResponse(content=[
        {
            "job_id": j["job_id"],
            "url": j["url"],
            "source": j["source"],
            "status": j["status"],
            "progress": j["progress"],
            "review_count": len(j["reviews"]),
            "created_at": j["created_at"],
        }
        for j in sorted(jobs.values(), key=lambda x: x["created_at"], reverse=True)
    ])


async def _run_scrape(job_id: str, url: str, source: Source):
    """Run scraping in a thread pool and update job state."""
    job = jobs[job_id]
    try:
        def progress_callback(count: int, message: str):
            job["progress"] = count
            job["message"] = message

        if source == Source.gmap:
            reviews = await asyncio.to_thread(scrape_gmap_reviews, url, progress_callback)
        else:
            reviews = await asyncio.to_thread(scrape_tripadvisor_reviews, url, progress_callback)

        job["reviews"] = reviews
        job["status"] = "done"
        job["progress"] = len(reviews)
        job["message"] = f"完了: {len(reviews)}件取得"
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        job["message"] = f"エラー: {str(e)}"


def _csv_response(reviews: list[dict]) -> StreamingResponse:
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=["review_id", "author", "rating", "date", "comment"])
    writer.writeheader()
    writer.writerows(reviews)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=reviews.csv"},
    )
