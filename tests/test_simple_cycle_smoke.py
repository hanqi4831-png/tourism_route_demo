"""Smoke tests for the simple-cycle Web runtime."""

from __future__ import annotations

import asyncio
import importlib
import json
import unittest

from models import PersonalizationSettings, UserRequest
from recommendation import top_k_recommendations
from route_filter import apply_personalized_hard_filters, filter_routes
from route_generator import RouteCandidate, filter_routes_by_personalization, generate_routes_from_patterns
from route_scoring import score_routes_for_recommendation
from seasonality import compute_dominant_supporting_season
from web_api import create_app
from web_service import RecommendationService


def _run_async(coro):
    return asyncio.run(coro)


async def _asgi_json_request(app, method: str, path: str, payload: dict | None = None):
    request_body = b""
    headers: list[tuple[bytes, bytes]] = []
    if payload is not None:
        request_body = json.dumps(payload).encode("utf-8")
        headers.extend(
            [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(request_body)).encode("ascii")),
            ]
        )

    messages: list[dict] = []
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": request_body, "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "state": {},
    }

    await app(scope, receive, send)

    status = next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    payload_data = json.loads(body.decode("utf-8")) if body else None
    return status, payload_data


class SimpleCycleSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = RecommendationService()
        cls.service.initialize()
        cls.app = create_app()
        _run_async(cls.app.router.startup())

    @classmethod
    def tearDownClass(cls) -> None:
        _run_async(cls.app.router.shutdown())

    def test_core_modules_import(self) -> None:
        for module_name in ("main", "web_api", "web_service"):
            with self.subTest(module=module_name):
                importlib.import_module(module_name)

    def test_service_recommend_returns_simple_cycle_fields(self) -> None:
        response = self.service.recommend(UserRequest())
        self.assertGreater(len(response["routes"]), 0)
        route = response["routes"][0]

        self.assertTrue(route["is_closed_loop"])
        self.assertTrue(route["is_simple_cycle"])
        self.assertIsInstance(route["cycle_signature"], list)
        self.assertIn("cycle_support", route)
        self.assertIn("cycle_tpi", route)
        self.assertIn("cycle_strength_global", route)
        self.assertTrue(route["display_route_summary"].startswith("Simple cycle route: "))
        self.assertIn("Simple cycle route", route["reason_tags"])

        for removed_field in (
            "route_structure_type",
            "has_repeated_pois",
            "repeat_ratio",
            "out_and_back_score",
            "repetitive_loop_score",
            "normalized_route_signature",
            "structure_quality_score",
            "repeat_ratio_penalty",
        ):
            self.assertNotIn(removed_field, route)

    def test_api_recommend_returns_200_and_simple_cycle_fields(self) -> None:
        status_code, payload = _run_async(_asgi_json_request(self.app, "POST", "/api/recommend", {}))

        self.assertEqual(status_code, 200)
        self.assertIsInstance(payload, dict)
        self.assertGreater(len(payload["routes"]), 0)

        route = payload["routes"][0]
        self.assertTrue(route["is_closed_loop"])
        self.assertTrue(route["is_simple_cycle"])
        self.assertIsInstance(route["cycle_signature"], list)
        self.assertTrue(route["display_route_summary"].startswith("Simple cycle route: "))
        self.assertNotIn("exclude_out_and_back_routes", payload["meta"])

    def test_compute_dominant_supporting_season_prefers_requested_season_on_tie(self) -> None:
        season = compute_dominant_supporting_season(
            supporting_trajectory_ids=frozenset({"t_spring", "t_winter"}),
            trajectory_season_lookup={
                "t_spring": "spring",
                "t_winter": "winter",
            },
            requested_season="winter",
        )
        self.assertEqual(season, "winter")

    def test_filter_routes_by_personalization_uses_requested_season_tiebreak(self) -> None:
        route = RouteCandidate(
            poi_route=("P1", "P2", "P1"),
            avg_pair_tpi=0.1,
            cycle_support=2,
            cycle_tpi=0.1,
            cycle_strength_global=0.1,
            supporting_trajectory_ids=frozenset({"t_spring", "t_winter"}),
            categories=("history", "history"),
            path_length=2,
            unique_poi_count=2,
            canonical_cycle_signature=("P1", "P2"),
        )
        poi_dict = {
            "P1": {"poi_name": "P1", "category": "history", "suitable_season": "all"},
            "P2": {"poi_name": "P2", "category": "history", "suitable_season": "all"},
        }

        result = filter_routes_by_personalization(
            routes=[route],
            poi_dict=poi_dict,
            trajectory_seasons={
                "t_spring": "spring",
                "t_winter": "winter",
            },
            requested_season="winter",
            start_poi=None,
            must_include_pois=[],
        )

        self.assertEqual(len(result.routes), 1)
        self.assertEqual(result.routes[0].dominant_supporting_season, "winter")
        self.assertEqual(result.routes[0].season_fit_score, 1.0)

    def test_neutral_named_ranking_pipeline_returns_scored_routes(self) -> None:
        state = self.service.state
        assert state is not None

        request = UserRequest()
        settings = PersonalizationSettings()
        routes = generate_routes_from_patterns(
            state.circular_patterns,
            state.poi_dict,
            config=self.service.config,
        )
        personalized = filter_routes_by_personalization(
            routes=routes,
            poi_dict=state.poi_dict,
            trajectory_seasons=state.trajectory_seasons,
            requested_season=request.requested_season,
            start_poi=request.start_poi,
            must_include_pois=request.must_include_pois,
            fallback_limit=max(self.service.config.top_k, 3),
            config=self.service.config,
        )
        filter_result = filter_routes(
            routes=personalized.routes,
            poi_dict=state.poi_dict,
            config=self.service.config,
            time_budget_hours=None,
        )
        hard_filter_result = apply_personalized_hard_filters(
            routes=filter_result.routes,
            poi_dict=state.poi_dict,
            config=self.service.config,
            request=request,
            settings=settings,
        )
        scored_routes = score_routes_for_recommendation(
            routes=hard_filter_result.routes,
            poi_dict=state.poi_dict,
            poi_popularity=state.poi_popularity,
            request=request,
            settings=settings,
            config=self.service.config,
            fallback_reason=personalized.fallback_reason,
        )
        recommendations = top_k_recommendations(
            scored_routes=scored_routes,
            top_k=self.service.config.top_k,
            start_poi=None,
            must_include_pois=None,
            similarity_threshold=self.service.config.topk_similarity_threshold,
        )

        self.assertGreater(len(recommendations), 0)
        self.assertTrue(recommendations[0].route.poi_route[0] == recommendations[0].route.poi_route[-1])


if __name__ == "__main__":
    unittest.main()
