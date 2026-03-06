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


@app.on_event("startup")
def cleanup_stale_jobs():
    """Mark running jobs older than 30 minutes as failed (stale from previous instance)."""
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    for job in db.list_jobs():
        if job.get("status") == "running":
            created = job.get("created_at", "")
            try:
                t = datetime.fromisoformat(created)
                if t < cutoff:
                    db.update_job(job["job_id"], status="failed",
                                  error="サーバー再起動によりタイムアウト",
                                  message="タイムアウト（30分超過）")
            except Exception:
                pass



class Source(str, Enum):
    google = "google"
    gmap = "gmap"  # backward compat
    tripadvisor = "tripadvisor"


class ScrapeRequest(BaseModel):
    url: str
    source: Source


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/scrape")
async def scrape_async(req: ScrapeRequest):
    # Check for duplicate URL (within 5 minutes)
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    for existing in db.list_jobs(limit=20):
        if (existing.get("url") == req.url
            and existing.get("status") == "running"
            and existing.get("created_at")):
            try:
                t = datetime.fromisoformat(existing["created_at"])
                if t > cutoff:
                    return JSONResponse(
                        content={"error": f"同じURLのジョブが実行中です (ID: {existing['job_id']})"},
                        status_code=409)
            except Exception:
                pass
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
        # Reviews available at GET /jobs/{id}/reviews
        if job.get("error"):
            resp["error"] = job["error"]
    return JSONResponse(content=resp)


@app.get("/jobs")
def list_jobs():
    return JSONResponse(content=db.list_jobs())



@app.get("/jobs/{job_id}/reviews")
def get_job_reviews(job_id: str):
    job = db.get_job(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    if job.get("status") != "done":
        return JSONResponse(content={"error": "Job not finished"}, status_code=400)
    reviews = db.get_job_reviews(job_id)
    return JSONResponse(content=reviews)

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

        def review_save_callback(reviews_batch: list[dict]):
            """Save reviews incrementally as they are collected."""
            db.save_review_batch(job_id, reviews_batch)

        if source in (Source.google, Source.gmap):
            coro = asyncio.to_thread(scrape_gmap_reviews, url, progress_callback, review_save_callback)
        else:
            coro = asyncio.to_thread(scrape_tripadvisor_reviews, url, progress_callback, review_save_callback)

        # 10 minute overall timeout
        try:
            reviews = await asyncio.wait_for(coro, timeout=600)
        except asyncio.TimeoutError:
            duration = int(_time.time() - _start)
            db.update_job(job_id, status="failed", error="10分タイムアウト", duration=duration,
                          message="10分タイムアウトで終了")
            db.append_log(job_id, "10分タイムアウトで強制終了")
            return

        # Reviews already saved incrementally via review_save_callback
        duration = int(_time.time() - _start)
        db.update_job(job_id, status="done", progress=len(reviews), duration=duration,
                      message=f"完了: {len(reviews)}件取得")
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
