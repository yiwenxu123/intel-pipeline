"""调度器与领域暂停配置测试。"""

from __future__ import annotations

from unittest.mock import patch

from engine.config import settings


def test_paused_domains_default_includes_china_africa():
    assert settings.is_domain_paused("china-africa")


def test_paused_domains_parsing(monkeypatch):
    monkeypatch.setattr(settings, "paused_domains", "china-africa, elderly-care ,")
    assert settings.get_paused_domains() == frozenset({"china-africa", "elderly-care"})
    assert not settings.is_domain_paused("other")


@patch("engine.pipeline.run_full_pipeline")
def test_run_pipeline_job_skips_paused(mock_pipe, monkeypatch):
    from scripts.scheduler import run_pipeline_job

    monkeypatch.setattr(settings, "paused_domains", "china-africa")
    run_pipeline_job("china-africa")
    mock_pipe.assert_not_called()


@patch("engine.domain.load_domain")
@patch("engine.pipeline.run_full_pipeline")
def test_run_pipeline_job_runs_active_domain(mock_pipe, mock_load, monkeypatch):
    from scripts.scheduler import run_pipeline_job

    monkeypatch.setattr(settings, "paused_domains", "china-africa")
    monkeypatch.setattr(settings, "domain", "elderly-care")
    mock_load.return_value.name = "elderly-care"
    mock_pipe.return_value.error = None
    mock_pipe.return_value.fetch = None
    mock_pipe.return_value.filter = None
    mock_pipe.return_value.duration_seconds = 1.0

    run_pipeline_job("elderly-care")
    mock_pipe.assert_called_once()
