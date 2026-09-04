"""Tests for transcription endpoints."""
import io
import wave


def create_wav_bytes(duration_ms=100, sample_rate=16000, frequency=440):
    """Create a simple WAV file in memory."""
    buffer = io.BytesIO()
    n_frames = int(sample_rate * duration_ms / 1000)
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Generate sine wave
        import math
        frames = []
        for i in range(n_frames):
            value = int(10000 * math.sin(2 * math.pi * frequency * i / sample_rate))
            frames.append(value.to_bytes(2, "little", signed=True))
        wf.writeframes(b"".join(frames))
    buffer.seek(0)
    return buffer.read()


class TestTranscribe:
    """Test transcription endpoints."""

    def test_transcribe_sync_success(self, client, auth_headers):
        """Test synchronous transcription endpoint."""
        wav_data = create_wav_bytes()
        files = {"file": ("test.wav", wav_data, "audio/wav")}
        response = client.post(
            "/api/v1/transcribe?language=id",
            files=files,
            headers=auth_headers
        )
        # Should succeed even with tiny model (may return empty text for silence)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data

    def test_transcribe_invalid_format(self, client, auth_headers):
        """Test transcription with invalid file format."""
        files = {"file": ("test.txt", b"not audio", "text/plain")}
        response = client.post(
            "/api/v1/transcribe?language=id",
            files=files,
            headers=auth_headers
        )
        assert response.status_code == 400

    def test_transcribe_empty_file(self, client, auth_headers):
        """Test transcription with empty file."""
        files = {"file": ("test.wav", b"", "audio/wav")}
        response = client.post(
            "/api/v1/transcribe?language=id",
            files=files,
            headers=auth_headers
        )
        assert response.status_code == 400

    def test_transcribe_batch_sync(self, client, auth_headers):
        """Test synchronous batch transcription."""
        wav_data = create_wav_bytes()
        files = [
            ("files", ("test1.wav", wav_data, "audio/wav")),
            ("files", ("test2.wav", wav_data, "audio/wav")),
        ]
        response = client.post(
            "/api/v1/transcribe-batch?language=id",
            files=files,
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["summary"]["total"] == 2

    def test_transcribe_batch_too_many_files(self, client, auth_headers):
        """Test batch with more than 20 files."""
        wav_data = create_wav_bytes()
        files = [
            ("files", (f"test{i}.wav", wav_data, "audio/wav"))
            for i in range(21)
        ]
        response = client.post(
            "/api/v1/transcribe-batch?language=id",
            files=files,
            headers=auth_headers
        )
        assert response.status_code == 400