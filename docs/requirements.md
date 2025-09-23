# System Requirements: Personal Cloud Transcriber

## 1. Project Goal

To create a high-performance, personal-use audio/video transcription service. The system will leverage a local machine for pre-processing and a powerful, GPU-enabled cloud instance for the actual speech-to-text conversion. This hybrid approach optimizes for speed and cost by performing lightweight tasks locally and offloading only the computationally intensive work to an on-demand cloud server.

## 2. Architectural Overview

The system is composed of two main components:

1.  **Local Client**: A Python script that runs on the user's machine. It is responsible for file selection, audio extraction, voice activity detection (VAD), and orchestrating the transcription process.
2.  **Cloud Worker**: A pre-built, containerized transcription server running on a cloud provider (e.g., GCP). It exposes a simple REST API to receive audio chunks and return transcribed text.

This architecture avoids the complexity of a full cloud-native data pipeline (e.g., storage buckets, triggers, message queues) and is ideal for an MVP focused on personal use.

## 3. Component Specifications

### 3.1. Local Client (`local_client.py`)

-   **Functionality**:
    -   **File Selection**: Interactively prompts the user to select an audio or video file from a local directory.
    -   **Audio Extraction**: Uses `ffmpeg` to convert the input file into a standardized format: 16kHz, 16-bit, mono WAV.
    -   **Voice Activity Detection (VAD)**: Uses a VAD model (e.g., Silero VAD) to split the WAV file into smaller audio chunks based on speech segments. This avoids transcribing silence and creates small, independent work units.
    -   **API Client**: Acts as an HTTP client to the Cloud Worker. It sends each audio chunk to the worker's API endpoint and collects the resulting text.
    -   **Orchestration**: Manages the process of sending all chunks, polling for results (if the API is asynchronous), and assembling the final transcript in the correct order.
    -   **Output**: Saves the final, full transcript as local `.txt` and `.json` files.
-   **Environment**:
    -   Runs within a local Python virtual environment (`venv`).
    -   Dependencies are managed via `requirements.txt` and include `requests`, `torch`, `torchaudio`, `soundfile`, and a VAD library.

### 3.2. Cloud Worker (Docker Container)

-   **Base Image**: To ensure stability and avoid dependency issues, the worker will be based on a well-maintained, pre-built Docker image such as `wordcab/wordcab-transcribe:latest`. This image comes with Python, CUDA, cuDNN, and `faster-whisper` pre-installed and configured.
-   **Functionality**:
    -   Exposes a REST API for transcription (e.g., `POST /api/v1/transcribe`).
    -   Accepts audio files via `multipart/form-data`.
    -   Utilizes `faster-whisper` with a large model (e.g., `large-v3`) for high-accuracy transcription.
    -   Leverages GPU acceleration (NVIDIA GPU, e.g., L4 or A100) via CUDA for high performance. The specific compute type (e.g., `float16`, `int8`) should be configurable.
-   **Deployment**:
    -   The worker will be managed locally for testing using `docker-compose.yml`.
    -   The `docker-compose` configuration will handle port mapping, GPU device allocation, and volume mounting for model caching to prevent re-downloads on restart.
    -   For cloud deployment, the same Docker image can be run on a GPU-enabled VM instance (e.g., GCP Compute Engine).

## 4. Workflow

1.  The user starts the Cloud Worker container locally using `docker-compose up`. The server starts and loads the transcription model into GPU memory.
2.  The user runs the `local_client.py` script in a separate terminal.
3.  The client prompts the user to select a media file.
4.  The client converts the file to a temporary WAV audio file.
5.  The client runs VAD on the WAV file, creating multiple smaller chunk files in a temporary directory.
6.  The client iterates through the chunks, sending each one via an HTTP POST request to the worker's `/transcribe` endpoint.
7.  The worker receives each chunk, transcribes it using `faster-whisper` on the GPU, and immediately returns the text in the HTTP response.
8.  The client receives the transcribed text for each chunk, stores it, and continues until all chunks are processed.
9.  The client assembles the text segments in the correct order to form the final transcript.
10. The client saves the transcript to local `.txt` and `.json` files.
