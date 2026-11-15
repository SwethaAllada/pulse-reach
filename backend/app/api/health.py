from fastapi import APIRouter, Response, status

from app.db.session import database_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
def health_db(response: Response) -> dict[str, str]:
    db = database_status()
    if db != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if db == "ok" else "degraded", "database": db}
