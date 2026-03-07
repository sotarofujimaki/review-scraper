"""Firestore-backed job store with in-memory fallback."""
import os
from datetime import datetime, timezone

_firestore_client = None
_USE_FIRESTORE = True

from config import FIRESTORE_COLLECTION as COLLECTION, FIRESTORE_BATCH_SIZE


def _get_db():
    global _firestore_client, _USE_FIRESTORE
    if not _USE_FIRESTORE:
        return None
    if _firestore_client is None:
        try:
            from google.cloud import firestore
            _firestore_client = firestore.Client()
        except Exception:
            _USE_FIRESTORE = False
            return None
    return _firestore_client


# In-memory fallback (for local dev)
_mem: dict[str, dict] = {}


def create_job(job_id: str, url: str, source: str) -> dict:
    job = {
        "job_id": job_id,
        "url": url,
        "source": source,
        "status": "running",
        "progress": 0,
        "message": "開始中...",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reviews": [],
        "error": None,
    }
    db = _get_db()
    if db:
        doc = db.collection(COLLECTION).document(job_id)
        # Store reviews separately as subcollection to avoid 1MB doc limit
        save = {k: v for k, v in job.items() if k != "reviews"}
        save["review_count"] = 0
        doc.set(save)
    _mem[job_id] = job
    return job


def update_job(job_id: str, **kwargs):
    # Update in-memory
    if job_id in _mem:
        _mem[job_id].update(kwargs)

    db = _get_db()
    if db:
        doc = db.collection(COLLECTION).document(job_id)
        # Don't write reviews list to main doc (use subcollection)
        update = {k: v for k, v in kwargs.items() if k != "reviews"}
        if "reviews" in kwargs:
            update["review_count"] = len(kwargs["reviews"])
        if update:
            doc.update(update)


def save_reviews(job_id: str, reviews: list[dict]):
    """Save reviews to Firestore subcollection in batches."""
    db = _get_db()
    if not db:
        return
    coll = db.collection(COLLECTION).document(job_id).collection("reviews")

    # Batch write (max 500 per batch)
    batch = db.batch()
    count = 0
    for i, review in enumerate(reviews):
        ref = coll.document(review.get("review_id") or str(i))
        batch.set(ref, review)
        count += 1
        if count >= FIRESTORE_BATCH_SIZE:
            batch.commit()
            batch = db.batch()
            count = 0
    if count > 0:
        batch.commit()


def save_review_batch(job_id: str, reviews: list[dict]):
    """Incrementally save a batch of reviews to Firestore subcollection."""
    db = _get_db()
    if not db or not reviews:
        return
    coll = db.collection(COLLECTION).document(job_id).collection("reviews")
    batch = db.batch()
    for review in reviews:
        ref = coll.document(review.get("review_id") or str(hash(str(review))))
        batch.set(ref, review)
    batch.commit()


def get_job(job_id: str) -> dict | None:
    # Always read from Firestore (worker may be on different instance)
    db = _get_db()
    if db:
        doc = db.collection(COLLECTION).document(job_id).get()
        if doc.exists:
            data = doc.to_dict()
            data["job_id"] = job_id
            # Update in-memory cache
            _mem[job_id] = data
            return data

    # Fallback to in-memory (no Firestore)
    if job_id in _mem:
        return _mem[job_id]
    return None


def get_job_reviews(job_id: str) -> list[dict]:
    # Try in-memory first
    if job_id in _mem and _mem[job_id].get("reviews"):
        return _mem[job_id]["reviews"]

    db = _get_db()
    if db:
        docs = db.collection(COLLECTION).document(job_id).collection("reviews").stream()
        return [d.to_dict() for d in docs]
    return []


def list_jobs(limit: int = 50) -> list[dict]:
    results = []
    db = _get_db()
    if db:
        query = (
            db.collection(COLLECTION)
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
        )
        for doc in query.stream():
            data = doc.to_dict()
            data["job_id"] = doc.id
            results.append(data)
    # Merge in-memory jobs not in Firestore results
    fs_ids = {r["job_id"] for r in results}
    for jid, job in _mem.items():
        if jid not in fs_ids:
            results.append({
                "job_id": job["job_id"],
                "url": job["url"],
                "source": job["source"],
                "status": job["status"],
                "progress": job["progress"],
                "review_count": len(job.get("reviews", [])),
                "created_at": job["created_at"],
            })
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results[:limit]


def delete_job(job_id: str):
    """Delete a job from Firestore and in-memory."""
    _mem.pop(job_id, None)
    db = _get_db()
    if db:
        doc_ref = db.collection(COLLECTION).document(job_id)
        # Delete subcollections (reviews + logs)
        for review in doc_ref.collection("reviews").limit(500).stream():
            review.reference.delete()
        for log in doc_ref.collection("logs").limit(500).stream():
            log.reference.delete()
        doc_ref.delete()


def append_log(job_id: str, message: str):
    """Append a timestamped log entry to the job."""
    entry = {"time": datetime.now(timezone.utc).isoformat(), "message": message}

    # In-memory
    if job_id in _mem:
        if "logs" not in _mem[job_id]:
            _mem[job_id]["logs"] = []
        _mem[job_id]["logs"].append(entry)

    # Firestore - store as subcollection
    db = _get_db()
    if db:
        db.collection(COLLECTION).document(job_id).collection("logs").add(entry)


def get_logs(job_id: str) -> list[dict]:
    """Get all log entries for a job."""
    # In-memory first
    if job_id in _mem and _mem[job_id].get("logs"):
        return _mem[job_id]["logs"]

    db = _get_db()
    if db:
        docs = (
            db.collection(COLLECTION).document(job_id)
            .collection("logs")
            .order_by("time")
            .stream()
        )
        return [d.to_dict() for d in docs]
    return []
