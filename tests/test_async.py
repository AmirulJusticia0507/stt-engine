"""Tests for async transcription and job status endpoints."""
from unittest.mock import MagicMock, patch


class TestAsyncTranscribe:
    """Test async transcription endpoints."""

    def test_transcribe_async(self, client, auth_headers):
        """Test submitting async transcription job."""
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

        # Mock Celery to avoid needing a running worker
        with patch("app.main.celery_app.send_task") as mock_send_task:
            mock_task = MagicMock()
            mock_task.id = "test-task-id-123"
            mock_send_task.return_value = mock_task

            response = client.post(
                "/api/v1/transcribe-async?language=id",
                files=files,
                headers=auth_headers
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "task_id" in data

    def test_transcribe_batch_async(self, client, auth_headers):
        """Test submitting async batch job."""
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
        wav_data = buffer.read()

        files = [
            ("files", ("test1.wav", wav_data, "audio/wav")),
            ("files", ("test2.wav", wav_data, "audio/wav")),
        ]

        with patch("app.main.celery_app.send_task") as mock_send_task:
            mock_task = MagicMock()
            mock_task.id = "test-batch-task-id"
            mock_send_task.return_value = mock_task

            response = client.post(
                "/api/v1/transcribe-batch-async?language=id",
                files=files,
                headers=auth_headers
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "task_id" in data

    def test_job_status(self, client, auth_headers):
        """Test checking job status."""
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

        with patch("app.main.celery_app.send_task") as mock_send_task, \
             patch("app.main.celery_app.AsyncResult") as mock_async_result:

            mock_task = MagicMock()
            mock_task.id = "test-task-id-123"
            mock_send_task.return_value = mock_task

            mock_result = MagicMock()
            mock_result.state = "SUCCESS"
            mock_result.ready.return_value = True
            mock_result.result = {"status": "success", "data": {"text": "test"}}
            mock_async_result.return_value = mock_result

            # Submit
            files = {"file": ("test.wav", buffer.read(), "audio/wav")}
            submit = client.post(
                "/api/v1/transcribe-async?language=id",
                files=files,
                headers=auth_headers
            )
            task_id = submit.json()["task_id"]

            # Check status
            response = client.get(f"/api/v1/jobs/{task_id}", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "data" in data
            assert data["data"]["task_id"] == task_id

    def test_list_jobs(self, client, auth_headers):
        """Test listing jobs."""
        response = client.get("/api/v1/jobs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "jobs" in data