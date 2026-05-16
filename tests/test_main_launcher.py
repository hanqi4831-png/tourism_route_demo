"""Tests for the main Web launcher entrypoint."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import main
import web_service


class MainLauncherTest(unittest.TestCase):
    def test_run_starts_browser_thread_and_uvicorn(self) -> None:
        with (
            patch("main._start_browser_thread") as start_browser_thread,
            patch("main.uvicorn.run") as uvicorn_run,
        ):
            main.run()

        start_browser_thread.assert_called_once_with(main.URL)
        uvicorn_run.assert_called_once_with(
            "web_api:app",
            host=main.HOST,
            port=main.PORT,
            reload=False,
        )

    def test_open_browser_when_ready_opens_default_browser(self) -> None:
        with (
            patch("main._wait_for_server_ready", return_value=True),
            patch("main.webbrowser.open", return_value=True) as open_browser,
        ):
            main._open_browser_when_ready(main.URL)

        open_browser.assert_called_once_with(main.URL)

    def test_open_browser_when_server_is_not_ready_skips_open(self) -> None:
        with (
            patch("main._wait_for_server_ready", return_value=False),
            patch("main.webbrowser.open") as open_browser,
        ):
            main._open_browser_when_ready(main.URL)

        open_browser.assert_not_called()

    def test_main_source_no_longer_contains_cli_entrypoint_calls(self) -> None:
        source = Path(main.__file__).read_text(encoding="utf-8")
        for token in (
            "input(",
            "collect_cli_user_request",
            "print_recommendations",
            "export_unified_results",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_web_service_uses_neutral_recommendation_names(self) -> None:
        source = Path(web_service.__file__).read_text(encoding="utf-8")
        self.assertIn("apply_personalized_hard_filters(", source)
        self.assertIn("score_routes_for_recommendation(", source)
        self.assertNotIn("apply_cli_hard_filters(", source)
        self.assertNotIn("score_routes_for_cli(", source)
        self.assertNotIn("CLIPersonalizationSettings", source)


if __name__ == "__main__":
    unittest.main()
