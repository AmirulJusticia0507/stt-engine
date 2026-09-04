Dokumentasi ini mencakup skenario **File Audio Uploading** maupun  **Real-time WebSocket Streaming** .


# Voice-to-Text (STT) Engine Documentation

Dokumentasi teknis untuk sistem Speech-to-Text berbasis **Faster-Whisper** dan **FastAPI**.

---

## 1. Prerequisites & Environment Setup

### System Requirements

* **OS:** Ubuntu 22.04 LTS / Debian 12
* **GPU:** NVIDIA GPU (Minimum 8GB VRAM untuk FP16 Large-v3-Turbo)
* **CUDA Version:** 12.x
* **Python:** 3.10+

### Dependencies Installation

```bash
# Update system & install ffmpeg (WAJIB untuk pemrosesan audio)
sudo apt update && sudo apt install -y ffmpeg

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Core Libraries
pip install fastapi uvicorn[standard] faster-whisper torch websockets python-multipart
```


2. Project Directory Structure

stt-engine/
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI entrypoint & router
│   ├── stt_engine.py       # Core Faster-Whisper wrapper
│   └── utils.py            # Audio processing utilities
├── models/                 # Cached model files
├── Dockerfile
├── requirements.txt
└── README.md

3. 

## Core Implementation Code

### `app/stt_engine.py` (Inference Manager)

```Python
import torch
from faster_whisper import WhisperModel
import logging

logging.basicConfig(level=logging.INFO)

class SpeechToTextEngine:
    def __init__(self, model_size: str = "large-v3-turbo", device: str = None, compute_type: str = "float16"):
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
          
        # Jika running di CPU, gunakan int8/float32
        if self.device == "cpu":
            compute_type = "int8"
          
        logging.info(f"Loading Whisper model '{model_size}' on {self.device} with {compute_type}...")
      
        # Inisialisasi model CTranslate2
        self.model = WhisperModel(
            model_size_or_path=model_size,
            device=self.device,
            compute_type=compute_type
        )
        logging.info("Model loaded successfully.")

    def transcribe_file(self, audio_path: str, language: str = "id"):
        """
        Transkripsi file audio utuh (Batch processing)
        """
        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True, # Silero VAD otomatis aktif untuk memotong silence
            vad_parameters=dict(min_silence_duration_ms=500)
        )
      
        results = []
        for segment in segments:
            results.append({
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": segment.text.strip()
            })
          
        return {
            "detected_language": info.language,
            "language_probability": round(info.language_probability, 2),
            "segments": results
        }

    def transcribe_stream_chunk(self, audio_bytes: bytes, language: str = "id"):
        """
        Transkripsi chunk data audio murni dari WebSocket stream
        """
        # Implementasi dekode byte array & pengolahan buffer
        pass

# Singleton Instance
stt_service = SpeechToTextEngine()
```

`app/main.py` (FastAPI Server)

```Python
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException
from app.stt_engine import stt_service
import shutil
import os
import uuid

app = FastAPI(
    title="Voice-to-Text Engine API",
    description="High-performance Speech-to-Text REST & WebSocket API",
    version="1.0.0"
)

TEMP_DIR = "/tmp/stt_audio"
os.makedirs(TEMP_DIR, exist_ok=True)

@app.get("/health")
def health_check():
    return {"status": "ok", "gpu_available": stt_service.device == "cuda"}

@app.post("/api/v1/transcribe")
async def transcribe_audio(file: UploadFile = File(...), language: str = "id"):
    """
    Endpoint HTTP POST untuk transkripsi file audio (.mp3, .wav, .m4a)
    """
    file_id = str(uuid.uuid4())
    extension = file.filename.split(".")[-1]
    temp_path = os.path.join(TEMP_DIR, f"{file_id}.{extension}")

    try:
        # Save temporary audio file
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Process Transcription
        result = stt_service.transcribe_file(temp_path, language=language)
        return {"status": "success", "data": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.websocket("/ws/v1/transcribe-stream")
async def websocket_transcribe(websocket: WebSocket, language: str = "id"):
    """
    Endpoint WebSocket untuk Transkripsi Real-Time Stream
    """
    await websocket.accept()
    try:
        while True:
            # menerima raw byte chunk audio dari client
            data = await websocket.receive_bytes()
          
            # Catatan: Di produksi, kumpulkan chunk hingga durasi VAD tercapai (~1-2 detik)
            # lalu jalankan stt_service.model.transcribe()
          
            # Response placeholder / feedback
            await websocket.send_json({
                "event": "chunk_received",
                "bytes_length": len(data)
            })
    except WebSocketDisconnect:
        print("Client disconnected from WebSocket")
```


4. Docker Deployment Setup

```Dockerfile
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Running with GPU Support

# Build image

docker build -t stt-engine:v1 .

# Run container dengan passthrough GPU NVIDIA

docker run --gpus all -d -p 8000:8000 --name stt-service stt-engine:v1

5. Client Integration Examples
   cURL (HTTP API)

```Shell
curl -X POST "http://localhost:8000/api/v1/transcribe?language=id" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/sample_audio.mp3"
```


---

Jika sistem ini akan dipakai di skala produksi ber-traffic tinggi, penggabungan **Celery + Redis** untuk *background task management* dan penerapan **Audio Normalization** (`ffmpeg` / `pydub`) pada layer *ingestion* sangat direkomendasikan agar kualitas sinyal audio lebih stabil sebelum diproses oleh model.

<FollowUp label="Mau ditambahkan skema Celery + Redis untuk antrean file berukuran besar?" query="Tolong tambahkan konfigurasi Celery dan Redis ke dalam dokumentasi untuk menangani antrean file audio yang panjang/besar."/>
