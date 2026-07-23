"""Tests for the FastAPI server endpoints and schedule management."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Import the app — we'll patch dependencies at module level
import exif_tagger.server as server_module
from exif_tagger.models.schema import ScheduleModel


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset global state before each test."""
    server_module._engine = None
    server_module._schedules.clear()
    server_module._scheduler = None
    # Reset schedules file
    schedules_file = Path("/app/schedules.json")
    if schedules_file.exists():
        schedules_file.unlink()


@pytest.fixture
def client(_reset_server_state):
    """Create a test client."""
    return TestClient(server_module.app)


class TestApiStatus:
    def test_status_no_session(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["processed"] == 0
        assert data["total"] == 0

    def test_status_running(self, client):
        with patch.object(server_module, '_get_engine') as mock_get:
            mock_engine = MagicMock()
            mock_engine.get_status.return_value = {
                "running": True, "processed": 5, "total": 10,
                "currentImage": "photo.jpg", "progressPct": 50.0,
                "stopRequested": False,
            }
            mock_engine.state.summary = None
            mock_get.return_value = mock_engine

            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["running"] is True


class TestApiStart:
    def test_start_no_running_session(self, client):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("root_directory: /tmp\nmodel:\n  base_url: http://test/v1\n  model_name: test\n")
            config_path = f.name

        original_config = server_module.CONFIG_PATH
        server_module.CONFIG_PATH = config_path

        try:
            with patch('exif_tagger.server.PipelineEngine') as mock_engine_cls:
                mock_instance = MagicMock()
                mock_instance.state.running = False
                mock_engine_cls.return_value = mock_instance

                resp = client.post("/api/start", json={"rootDirectory": "/tmp/images", "maxImages": 50})
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "started"
        finally:
            server_module.CONFIG_PATH = original_config
            os.unlink(config_path)

    def test_start_already_running(self, client):
        # Set _engine to a state where running=True (the endpoint checks the global directly)
        mock_engine = MagicMock()
        mock_engine.state.running = True
        server_module._engine = mock_engine

        resp = client.post("/api/start", json={})
        assert resp.status_code == 409


class TestApiStop:
    def test_stop_no_session(self, client):
        with patch.object(server_module, '_get_engine') as mock_get:
            mock_engine = MagicMock()
            mock_engine.state.running = False
            mock_get.return_value = mock_engine

            resp = client.post("/api/stop")
            assert resp.status_code == 400

    def test_stop_with_session(self, client):
        with patch.object(server_module, '_get_engine') as mock_get:
            mock_engine = MagicMock()
            mock_engine.state.running = True
            mock_engine.stop.return_value = {"status": "stopped", "processed": 10}
            mock_get.return_value = mock_engine

            resp = client.post("/api/stop")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "stopped"


class TestApiConfig:
    def test_get_config(self, client):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""root_directory: /tmp/images
model:
  base_url: http://test/v1
  model_name: gpt-4o
tags:
  landscape:
    description: Pictures of landscapes
    threshold: 0.7
exclude_patterns: []
""")
            config_path = f.name

        original_config = server_module.CONFIG_PATH
        server_module.CONFIG_PATH = config_path

        try:
            resp = client.get("/api/config")
            assert resp.status_code == 200
            data = resp.json()
            assert data["root_directory"] == "/tmp/images"
            assert "landscape" in data["tags"]
            assert data["tags"]["landscape"]["threshold"] == 0.7
        finally:
            server_module.CONFIG_PATH = original_config
            os.unlink(config_path)


class TestApiSchedules:
    def test_list_empty_schedules(self, client):
        resp = client.get("/api/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    def test_create_schedule(self, client):
        with patch.object(server_module, '_setup_scheduler'):
            resp = client.post("/api/schedule", json={
                "name": "Daily scan",
                "folder": "/data/images",
                "interval_hours": 6,
                "enabled": True,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert "id" in data

    def test_delete_schedule(self, client):
        with patch.object(server_module, '_setup_scheduler'):
            # First create a schedule
            resp = client.post("/api/schedule", json={
                "name": "Test",
                "folder": "/data/images",
                "interval_hours": 1,
            })
            sid = resp.json()["id"]

            # Then delete it
            resp = client.delete(f"/api/schedule/{sid}")
            assert resp.status_code == 200
            assert resp.json()["status"] == "deleted"

    def test_delete_nonexistent_schedule(self, client):
        resp = client.delete("/api/schedule/nonexistent_id")
        assert resp.status_code == 404


class TestScheduleModel:
    def test_schedule_model_defaults(self):
        s = ScheduleModel(name="test", folder="/data/images")
        assert s.enabled is True
        assert s.last_run_at is None
        assert s.interval_hours is None

    def test_schedule_cron_validation(self):
        with pytest.raises(Exception):
            ScheduleModel(
                name="bad cron",
                folder="/data/images",
                cron_expression="invalid"  # Not 5 fields
            )


class TestComputeNextRun:
    def test_interval_hours(self):
        from datetime import datetime, timezone, timedelta

        schedule = ScheduleModel(name="test", folder="/data", interval_hours=6)
        next_run = server_module._compute_next_run(schedule)
        assert next_run is not None

        # Parse and verify it's roughly 6 hours ahead
        run_time = datetime.fromisoformat(next_run)
        now = datetime.now(timezone.utc).replace(microsecond=0, second=0)
        diff = (run_time - now).total_seconds() / 3600
        assert 5.9 <= diff <= 7.0

    def test_cron_expression(self):
        schedule = ScheduleModel(
            name="daily",
            folder="/data",
            cron_expression="0 2 * * *"
        )
        next_run = server_module._compute_next_run(schedule)
        assert next_run is not None
