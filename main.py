"""FastAPI web service for scraping reviews from Google Maps and TripAdvisor."""
import asyncio
import csv
import io
import uuid
from enum import Enum

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel

from scraper.gmap import scrape_gmap_reviews
from scraper.tripadvisor import scrape_tripadvisor_reviews
import db

app = FastAPI(title="Review Scraper API")


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
    job_id = str(uuid.uuid4())[:8]
    db.create_job(job_id, req.url, req.source.value)
    asyncio.create_task(_run_scrape(job_id, req.url, req.source))
    return JSONResponse(content={"job_id": job_id, "status": "running"}, status_code=202)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    resp = {
        "job_id": job.get("job_id", job_id),
        "url": job.get("url", ""),
        "source": job.get("source", ""),
        "status": job.get("status", ""),
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "created_at": job.get("created_at", ""),
        "review_count": job.get("review_count", len(job.get("reviews", []))),
        "duration": job.get("duration"),
    }
    if job.get("status") in ("done", "failed"):
        if job.get("status") == "done":
            resp["reviews"] = db.get_job_reviews(job_id)
        if job.get("error"):
            resp["error"] = job["error"]
    return JSONResponse(content=resp)


@app.get("/jobs/{job_id}/csv")
def get_job_csv(job_id: str):
    job = db.get_job(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    if job.get("status") != "done":
        return JSONResponse(content={"error": "Job not finished"}, status_code=400)
    reviews = db.get_job_reviews(job_id)
    return _csv_response(reviews)


@app.get("/jobs")
def list_jobs():
    return JSONResponse(content=db.list_jobs())


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    db.delete_job(job_id)
    return JSONResponse(content={"ok": True})


@app.get("/jobs/{job_id}/logs")
def get_job_logs(job_id: str):
    logs = db.get_logs(job_id)
    return JSONResponse(content=logs)


async def _run_scrape(job_id: str, url: str, source: Source):
    import time as _time
    _start = _time.time()
    try:
        def progress_callback(count: int, message: str):
            db.update_job(job_id, progress=count, message=message, review_count=count)
            db.append_log(job_id, message)

        if source == Source.gmap:
            reviews = await asyncio.to_thread(scrape_gmap_reviews, url, progress_callback)
        else:
            reviews = await asyncio.to_thread(scrape_tripadvisor_reviews, url, progress_callback)

        # Save reviews to Firestore subcollection
        db.save_reviews(job_id, reviews)
        # Update in-memory + Firestore doc
        duration = int(_time.time() - _start)
        db.update_job(job_id, status="done", progress=len(reviews), duration=duration,
                      message=f"完了: {len(reviews)}件取得", reviews=reviews)
    except Exception as e:
        duration = int(_time.time() - _start)
        db.update_job(job_id, status="failed", error=str(e), duration=duration,
                      message=f"エラー: {str(e)}")


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
