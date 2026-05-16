"""FastAPI entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from models import UserRequest
from web_service import RecommendationService


class RecommendRequest(BaseModel):
    preferred_categories: List[str] = Field(default_factory=list)
    season: Optional[str] = None
    start_poi_id: Optional[str] = None
    must_visit_poi_ids: List[str] = Field(default_factory=list)
    time_budget_hours: Optional[float] = Field(default=None, gt=0)
    top_k: Optional[int] = Field(default=None, ge=1)
    hard_filter_keys: List[str] = Field(default_factory=list)
    soft_rank_groups: List[List[str]] = Field(default_factory=list)


def create_app() -> FastAPI:
    app = FastAPI(title="Tourism Route Demo API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    service = RecommendationService()
    frontend_dir = Path(__file__).resolve().parent / "frontend"
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

    @app.on_event("startup")
    def startup_event() -> None:
        try:
            service.initialize()
        except ValueError:
            # Keep the app available so the user can import data from the UI.
            return None

    @app.get("/api/categories")
    def get_categories() -> List[str]:
        try:
            return service.get_categories()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/pois")
    def get_pois() -> List[dict[str, Any]]:
        try:
            return service.get_pois()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/stats")
    def get_stats() -> dict[str, Any]:
        try:
            return service.get_stats()
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/recommend")
    def post_recommend(payload: RecommendRequest) -> dict[str, Any]:
        request = UserRequest(
            preferred_categories=payload.preferred_categories,
            requested_season=payload.season,
            start_poi=payload.start_poi_id,
            must_include_pois=payload.must_visit_poi_ids,
            time_budget_hours=payload.time_budget_hours,
            hard_filter_keys=payload.hard_filter_keys,
            soft_rank_groups=payload.soft_rank_groups,
        )
        try:
            return service.recommend(request=request, top_k=payload.top_k)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/data/import")
    async def import_data(
        poi_file: UploadFile = File(...), trajectory_file: UploadFile = File(...)
    ) -> dict[str, Any]:
        try:
            poi_bytes = await poi_file.read()
            traj_bytes = await trajectory_file.read()
            if not poi_bytes or not traj_bytes:
                raise ValueError("Uploaded files are empty. Check poi.csv and trajectory.csv.")
            return service.import_data_from_csv_bytes(
                poi_csv_bytes=poi_bytes,
                trajectory_csv_bytes=traj_bytes,
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Data import failed: {exc}") from exc

    @app.get("/")
    def get_index() -> FileResponse:
        return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()
