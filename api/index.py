"""Vercel serverless entrypoint for FastAPI.

Vercel Python runtime looks for `app` variable inside `api/*.py`.
We re-export the main FastAPI app so routes can point here.
"""
from app.main import app


@app.middleware("http")
async def _restore_vercel_path(request, call_next):
    """Jika Vercel meneruskan path hasil rewrite (/api/index...),
    kembalikan ke path asli agar routing FastAPI cocok."""
    p = request.scope.get("path", "")
    if p == "/api/index":
        request.scope["path"] = "/"
    elif p.startswith("/api/index/"):
        request.scope["path"] = p[len("/api/index"):]
    return await call_next(request)
