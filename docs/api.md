# Whisper Transcription Service API

This document describes the API for the asynchronous transcription service.

## Endpoints

### 1. Health Check

- **Endpoint:** `GET /health`
- **Description:** Checks if the service is running and the model is loaded.
- **Success Response (200 OK):**
  ```json
  {
    "status": "ok" or "loading",
    "queue_size": int,
    "device": "cuda" or "cpu"
  }
  ```
  - `status`: "ok" if the model is loaded and the service is ready; "loading" otherwise.
  - `queue_size`: The current number of tasks in the transcription queue.
  - `device`: The compute device being used for transcription.

### 2. Enqueue Chunk

- **Endpoint:** `POST /enqueue_chunk`
- **Description:** Accepts an audio file and adds it to the transcription queue.
- **Request Body:** `multipart/form-data` with a single field:
  - `file`: The audio file to be transcribed.
- **Success Response (200 OK):**
  ```json
  {
    "status": "accepted",
    "chunk_id": "string (uuid)"
  }
  ```
  - `chunk_id`: A unique identifier for the transcription task. This ID should be used to poll for the result.
- **Error Response (503 Service Unavailable):** Returned if the task queue is full.

### 3. Get Result

- **Endpoint:** `GET /get_result/{chunk_id}`
- **Description:** Retrieves the status and result of a transcription task.
- **URL Parameters:**
  - `chunk_id`: The unique ID of the task.
- **Success Response (200 OK):**
  ```json
  {
    "status": "queued" or "completed" or "error",
    "text": "The transcribed text.",
    "message": "An error message."
  }
  ```
  - `status`:
    - `queued`: The task is waiting to be processed.
    - `completed`: The task has been successfully transcribed. The `text` field will be present.
    - `error`: An error occurred during processing. The `message` field will be present.
- **Error Response (404 Not Found):** Returned if the `chunk_id` does not exist.
