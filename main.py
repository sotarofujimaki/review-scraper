import os
"""FastAPI web service for scraping reviews from Google Maps and TripAdvisor."""
import asyncio
import re
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

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



# --- Build info ---
_BUILD_TIMESTAMP = ""
try:
    with open("/tmp/.build-timestamp", "r") as _bf:
        _BUILD_TIMESTAMP = _bf.read().strip()
except Exception:
    pass
_REVISION = os.environ.get("K_REVISION", "local")

@app.get("/build-info")
async def build_info():
    return {"revision": _REVISION, "build_timestamp": _BUILD_TIMESTAMP}

@app.get("/favicon.svg")
def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


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
            and existing.get("status") in (JobStatus.running, "running")
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
        **({"last_screenshot": job["last_screenshot"]} if job.get("last_screenshot") else {}),
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








@app.post("/admin/flush-instances")
async def flush_instances():
    """全runningジョブを停止し、旧インスタンスを解放する。"""
    flushed = []
    for job in db.list_jobs():
        if job.get("status") in ("running", JobStatus.running):
            db.update_job(job["job_id"], status=JobStatus.cancelled, message="インスタンスフラッシュにより停止")
            db.append_log(job["job_id"], "インスタンスフラッシュにより停止")
            flushed.append(job["job_id"])
    return JSONResponse(content={"ok": True, "flushed": flushed, "count": len(flushed)})

@app.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    """Internal: re-run a failed job on a new instance (same job_id)."""
    job = db.get_job(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    url = job.get("url", "")
    source_str = job.get("source", "")
    try:
        source = Source(source_str)
    except ValueError:
        return JSONResponse(content={"error": f"Invalid source: {source_str}"}, status_code=400)
    db.update_job(job_id, status=JobStatus.running, message="リトライ開始（新インスタンス）")
    db.append_log(job_id, "新インスタンスでリトライ開始")
    asyncio.create_task(_run_scrape(job_id, url, source))
    return JSONResponse(content={"ok": True, "job_id": job_id}, status_code=202)

@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    if job.get("status") != JobStatus.running:
        return JSONResponse(content={"error": "Job is not running"}, status_code=400)
    db.update_job(job_id, status=JobStatus.cancelled, message="ユーザーにより停止")
    db.append_log(job_id, "ジョブ停止（ユーザー操作）")
    return JSONResponse(content={"ok": True, "job_id": job_id, "status": "cancelled"})

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

    _progress_counter = [0]
    def on_progress(count: int, message: str):
        _progress_counter[0] += 1
        # Check cancellation every 5 calls
        if _progress_counter[0] % 5 == 0:
            try:
                job = db.get_job(job_id)
                if job and job.get('status') in ('cancelled', JobStatus.cancelled):
                    raise RuntimeError('ジョブが停止されました')
            except RuntimeError:
                raise
            except Exception:
                pass  # Firestore error shouldn't kill scraping
        # Gyazo URLがあればlast_screenshotに保存
        extra = {}
        gyazo_match = re.search(r'📸\s*(https://gyazo\.com/[a-f0-9]+)', message)
        if gyazo_match:
            extra['last_screenshot'] = gyazo_match.group(1)
        # Always update status (lightweight)
        try:
            db.update_job(job_id, progress=count, message=message, review_count=count, **extra)
        except Exception:
            pass
        # Log every 3rd call to reduce Firestore writes
        if _progress_counter[0] % 3 == 0 or 'エラー' in message or '完了' in message or '開始' in message or '検出' in message:
            try:
                db.append_log(job_id, message)
            except Exception:
                pass

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
        duration = int(_time.time() - start)
        db.update_job(job_id, status=JobStatus.failed, error=str(e),
                      duration=duration,
                      message=f"エラー: {e}")
        # 失敗時にインスタンス切り替えリトライ（同じjob_id、最大1回）
        job = db.get_job(job_id)
        retry_count = job.get("retry_count", 0) if job else 0
        if retry_count < 2:
            try:
                import httpx, os
                db.update_job(job_id, status=JobStatus.running, retry_count=retry_count + 1,
                              message=f"インスタンス切替リトライ中...")
                db.append_log(job_id, f"インスタンス切替リトライ (失敗理由: {str(e)[:80]})")
                port = os.environ.get("PORT", "8080")
                # Self-call to get a new instance (concurrency=1)
                httpx.post(f"http://localhost:{port}/jobs/{job_id}/retry",
                           json={"url": url, "source": source.value},
                           timeout=5.0)
            except Exception as retry_err:
                db.append_log(job_id, f"リトライ失敗: {retry_err}")
                db.update_job(job_id, status=JobStatus.failed)
