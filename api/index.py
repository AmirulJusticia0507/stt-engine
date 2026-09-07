"""Vercel serverless entrypoint for FastAPI.

Vercel Python runtime looks for `app` variable inside `api/*.py`.
We re-export the main FastAPI app so rewrites can point here.
"""
from app.main import app  # noqa: F401
