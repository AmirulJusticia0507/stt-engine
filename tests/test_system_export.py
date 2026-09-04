"""Tests for system/model and export endpoints."""
import pytest


class TestSystem:
    """Test system and model endpoints."""

    def test_system_info(self, client, auth_headers):
        """Test system info endpoint."""
        response = client.get("/api/v1/system", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data
        assert "model" in data["data"]
        assert "device" in data["data"]

    def test_get_model_list(self, client, auth_headers):
        """Test that model switching works."""
        response = client.post(
            "/api/v1/system/model",
            json={"model": "tiny"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["model"] == "tiny"

    def test_invalid_model(self, client, auth_headers):
        """Test invalid model rejection."""
        response = client.post(
            "/api/v1/system/model",
            json={"model": "invalid-model"},
            headers=auth_headers
        )
        assert response.status_code == 400


class TestExport:
    """Test export endpoints."""

    def test_export_txt(self, client, auth_headers):
        """Test exporting as TXT."""
        # First create some history by transcribing
        import io
        import math
        import wave
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            frames = [int(1000 * math.sin(2 * math.pi * 440 * i / 16000)).to_bytes(2, "little", signed=True) for i in range(1600)]
            wf.writeframes(b"".join(frames))
        buffer.seek(0)

        files = {"file": ("test.wav", buffer.read(), "audio/wav")}
        client.post("/api/v1/transcribe?language=id", files={"file": ("test.wav", buffer.read(), "audio/wav")}, headers=auth_headers)
        buffer.seek(0)

        # Get history to find item ID
        hist = client.get("/api/v1/history", headers=auth_headers)
        items = hist.json()["data"]
        if not items:
            pytest.skip("No history items to export")
        item_id = items[0]["id"]

        # Export TXT
        response = client.get(
            f"/api/v1/history/{item_id}/export?format=txt",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

    def test_export_srt(self, client, auth_headers):
        """Test exporting as SRT."""
        hist = client.get("/api/v1/history", headers=auth_headers)
        items = hist.json()["data"]
        if not items:
            pytest.skip("No history items to export")
        item_id = items[0]["id"]

        response = client.get(
            f"/api/v1/history/{item_id}/export?format=srt",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-subrip"

    def test_export_vtt(self, client, auth_headers):
        """Test exporting as VTT."""
        hist = client.get("/api/v1/history", headers=auth_headers)
        items = hist.json()["data"]
        if not items:
            pytest.skip("No history items to export")
        item_id = items[0]["id"]

        response = client.get(
            f"/api/v1/history/{item_id}/export?format=vtt",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/vtt"

    def test_export_invalid_format(self, client, auth_headers):
        """Test invalid export format."""
        hist = client.get("/api/v1/history", headers=auth_headers)
        items = hist.json()["data"]
        if not items:
            pytest.skip("No history items to export")
        item_id = items[0]["id"]

        response = client.get(
            f"/api/v1/history/{item_id}/export?format=pdf",
            headers=auth_headers
        )
        assert response.status_code == 400

    def test_export_requires_auth(self, client):
        """Test export requires authentication."""
        response = client.get("/api/v1/history/1/export?format=txt")
        assert response.status_code == 401