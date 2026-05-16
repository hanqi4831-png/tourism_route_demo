"""Static checks for the Windows one-click startup contract."""

from __future__ import annotations

import unittest
from pathlib import Path


class WindowsStartupContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parent.parent

    def test_start_bat_bootstraps_venv_and_runs_main(self) -> None:
        start_bat = self.repo_root / "start.bat"
        self.assertTrue(start_bat.exists(), "start.bat should exist in the repo root")

        content = start_bat.read_text(encoding="utf-8")
        for token in (
            ".venv",
            "activate.bat",
            "requirements.txt",
            "main.py",
            "pip install",
        ):
            with self.subTest(token=token):
                self.assertIn(token, content)

        self.assertNotIn("D:\\编程\\编译器\\python\\python.exe", content)

    def test_readme_is_windows_focused(self) -> None:
        readme = (self.repo_root / "README.md").read_text(encoding="utf-8")

        for token in (
            "Windows",
            "start.bat",
            "requirements.txt",
            "python main.py",
            "http://127.0.0.1:8000/",
        ):
            with self.subTest(token=token):
                self.assertIn(token, readme)

        for removed_token in (
            "start.ps1",
            "start.sh",
            "macOS / Linux",
            "Linux 启动说明",
        ):
            with self.subTest(token=removed_token):
                self.assertNotIn(removed_token, readme)

    def test_requirements_include_direct_runtime_imports(self) -> None:
        requirements = (self.repo_root / "requirements.txt").read_text(encoding="utf-8")
        for package in ("fastapi", "uvicorn", "pydantic", "python-multipart"):
            with self.subTest(package=package):
                self.assertIn(package, requirements)


if __name__ == "__main__":
    unittest.main()
