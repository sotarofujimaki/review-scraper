"""FastAPI web service for scraping reviews from Google Maps and TripAdvisor."""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse

from config import JOB_TIMEOUT_SECONDS, STALE_JOB_MINUTES, DUPLICATE_URL_MINUTES
from models import Source, ScrapeRequest, JobStatus
from scraper.google import scrape_google_reviews
from scraper.tripadvisor import scrape_tripadvisor_reviews
import db

app = FastAPI(title="Review Scraper API")


@app.on_event("startup")
def cleanup_stale_jobs():
    """Mark running jobs older than threshold as failed (stale from previous instance)."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_JOB_MINUTES)
    for job in db.list_jobs():
        if job.get("status") == JobStatus.running:
            try:
                t = datetime.fromisoformat(job.get("created_at", ""))
                if t < cutoff:
                    db.update_job(job["job_id"], status=JobStatus.failed,
                                  error="サーバー再起動によりタイムアウト",
                                  message=f"タイムアウト（{STALE_JOB_MINUTES}分超過）")
            except Exception:
                pass


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/scrape")
async def scrape_async(req: ScrapeRequest):
    if not req.url:
        return JSONResponse(content={"detail": "url is required"}, status_code=400)

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=DUPLICATE_URL_MINUTES)
    for existing in db.list_jobs(limit=20):
        if (existing.get("url") == req.url
            and existing.get("status") == JobStatus.running
            and existing.get("created_at")):
            try:
                if datetime.fromisoformat(existing["created_at"]) > cutoff:
                    return JSONResponse(
                        content={"error": f"同じURLのジョブが実行中です (ID: {existing['job_id']})"},
                        status_code=409)
            except Exception:
                pass

    job_id = uuid.uuid4().hex[:8]
    db.create_job(job_id, req.url, req.source.value)
    asyncio.create_task(_run_scrape(job_id, req.url, req.source))
    return JSONResponse(content={"job_id": job_id, "status": JobStatus.running}, status_code=202)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    return JSONResponse(content={
        "job_id": job.get("job_id", job_id),
        "url": job.get("url", ""),
        "source": job.get("source", ""),
        "status": job.get("status", ""),
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "created_at": job.get("created_at", ""),
        "review_count": job.get("review_count", 0),
        "duration": job.get("duration"),
        **({"error": job["error"]} if job.get("error") else {}),
    })


@app.get("/jobs")
def list_jobs():
    return JSONResponse(content=db.list_jobs())


@app.get("/jobs/{job_id}/reviews")
def get_job_reviews(job_id: str):
    job = db.get_job(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    if job.get("status") != JobStatus.done:
        return JSONResponse(content={"error": "Job not finished"}, status_code=400)
    return JSONResponse(content=db.get_job_reviews(job_id))


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    db.delete_job(job_id)
    return JSONResponse(content={"ok": True})


@app.get("/jobs/{job_id}/logs")
def get_job_logs(job_id: str):
    return JSONResponse(content=db.get_logs(job_id))


async def _run_scrape(job_id: str, url: str, source: Source):
    import time as _time
    start = _time.time()

    def on_progress(count: int, message: str):
        db.update_job(job_id, progress=count, message=message, review_count=count)
        db.append_log(job_id, message)

    def on_reviews(batch: list[dict]):
        db.save_review_batch(job_id, batch)

    try:
        scraper = scrape_google_reviews if source == Source.google else scrape_tripadvisor_reviews
        reviews = await asyncio.wait_for(
            asyncio.to_thread(scraper, url, on_progress, on_reviews),
            timeout=JOB_TIMEOUT_SECONDS,
        )
        db.update_job(job_id, status=JobStatus.done, progress=len(reviews),
                      duration=int(_time.time() - start),
                      message=f"完了: {len(reviews)}件取得")
    except asyncio.TimeoutError:
        db.update_job(job_id, status=JobStatus.failed,
                      error=f"{JOB_TIMEOUT_SECONDS // 60}分タイムアウト",
                      duration=int(_time.time() - start),
                      message=f"{JOB_TIMEOUT_SECONDS // 60}分タイムアウトで終了")
        db.append_log(job_id, f"{JOB_TIMEOUT_SECONDS // 60}分タイムアウトで強制終了")
    except Exception as e:
        db.update_job(job_id, status=JobStatus.failed, error=str(e),
                      duration=int(_time.time() - start),
                      message=f"エラー: {e}")
