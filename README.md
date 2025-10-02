# Whisper Transcriber: A Distributed Audio Transcription System

This is a high-performance, distributed system for asynchronous transcription of long audio and video files using the Whisper model. The architecture is designed for scalability and cost-effectiveness by processing audio chunks in parallel across multiple GPU workers deployed on Google Cloud Run.

## What Problem Does It Solve?

Transcribing long audio recordings (e.g., interviews, lectures, meetings) is a slow and computationally expensive process. Running it locally on a CPU can be time-consuming, and while using a single GPU is faster, it doesn't effectively parallelize the task.

This project solves this problem by providing an architecture that:

1.  **Uses Resources Efficiently:** Automatically splits audio into smaller chunks using a Voice Activity Detector (VAD), discarding silence and sending only meaningful segments for processing.
2.  **Scales Horizontally:** Allows audio to be processed in parallel across multiple independent GPU workers. System performance can be increased simply by adding more workers.
3.  **Is Asynchronous:** The client submits jobs without waiting for them to complete and polls for their status later. This allows the system to be integrated into more complex workflows.
4.  **Is Cloud-Optimized:** Leverages Google Cloud Run with GPUs, enabling a pay-per-use model where you only pay for the actual processing time. It can scale down to zero, minimizing costs.

## Architectural Decisions

The system consists of three key components:

### 1. Client (`local_client.py`, `gcp_client.py`)

-   **Purpose:** A user-facing interface for interacting with the system.
-   **Technologies:** Python, `ffmpeg`, `requests`, `torchaudio`, `silero-vad`.
-   **Workflow:**
    1.  Takes an audio or video file as input.
    2.  Uses `ffmpeg` to extract the audio track into a 16 kHz WAV format.
    3.  Uses the **Silero VAD** model to detect speech segments and splits the audio into small chunks.
    4.  Implements **client-side load balancing** by distributing the chunks among available workers via the proxy server.
    5.  Asynchronously sends chunks for processing and polls for their status.
    6.  Once all tasks are complete, it assembles the results into a single text (`.txt`) file and a detailed (`.json`) file with timestamps.

### 2. Proxy Server (`proxy_server.py`)

-   **Purpose:** A single entry point and gateway for all workers.
-   **Technologies:** Flask, Google Cloud Auth.
-   **Key Functions:**
    1.  **Routing:** Receives requests from the client and forwards them to a specific worker instance on Google Cloud Run based on the `worker_id` in the URL.
    2.  **Authentication:** Abstracts the complexity of authenticating with secure Cloud Run services. It automatically obtains and caches an **Identity Token** from Google and adds it to the `Authorization` header of the forwarded request.
    3.  **Security:** Implements basic protection with an API key (`X-API-Key`).

### 3. Worker (`worker/main.py`)

-   **Purpose:** The core component that performs the transcription.
-   **Technologies:** FastAPI, `faster-whisper`, `asyncio`, Docker.
-   **Architecture:**
    1.  **Asynchronous API:** Built on FastAPI for high performance.
    2.  **Internal Queue:** Uses an `asyncio.Queue` to manage tasks. Transcription requests are non-blocking and are placed in the queue.
    3.  **Background Processing:** A separate `asyncio` background task pulls jobs from the queue and processes them one by one.
    4.  **Efficient Transcription:** Uses the `faster-whisper` library with the `large-v3` model, optimized for GPU execution with `float16` computation.
    5.  **Isolation:** Each worker is independent and fault-tolerant. A failure in one worker does not affect the others. It is deployed as a Docker container on Google Cloud Run.

## Interaction Diagram

```mermaid
sequenceDiagram
    participant C as Client
    participant P as Proxy Server
    participant W1 as Worker 1 (GPU)
    participant W2 as Worker 2 (GPU)
    participant WN as Worker N (GPU)

    C->>C: Split audio into chunks (VAD)
    loop for each chunk
        C->>P: POST /enqueue_chunk (worker_id=i, audio_chunk)
        P->>Wi: (GCP Auth) POST /enqueue_chunk (audio_chunk)
        Wi-->>P: {"status": "accepted", "chunk_id": "..."}
        P-->>C: {"status": "accepted", "chunk_id": "..."}
    end

    loop until all tasks are complete
        C->>P: GET /get_result/{chunk_id} (worker_id=i)
        P->>Wi: (GCP Auth) GET /get_result/{chunk_id}
        alt Task is queued
            Wi-->>P: {"status": "queued"}
            P-->>C: {"status": "queued"}
        else Task is completed
            Wi-->>P: {"status": "completed", "result": "..."}
            P-->>C: {"status": "completed", "result": "..."}
        end
    end
    C->>C: Assemble all results into one file
