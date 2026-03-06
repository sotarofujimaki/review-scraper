"""Pydantic models for type safety."""
from pydantic import BaseModel
from enum import Enum
from typing import Optional


class Source(str, Enum):
    google = "google"
    tripadvisor = "tripadvisor"


class ScrapeRequest(BaseModel):
    url: str
    source: Source


class Review(BaseModel):
    review_id: str = ""
    author: str = ""
    rating: str = ""
    posted_at: str = ""
    comment: str = ""


class JobStatus(str, Enum):
    running = "running"
    done = "done"
    failed = "failed"
