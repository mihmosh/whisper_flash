import os
import asyncio
import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from faster_whisper import WhisperModel
import torch
import logging
from typing import Dict, Any

# --- Configuration ---
MODEL_SIZE = "large-v3"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Application State ---
app = FastAPI(
    title="Whisper Transcription Service",
    description="An asynchronous API for transcribing audio files using faster-whisper.",
    version="1.0.0",
)
model: WhisperModel = None
task_queue = asyncio.Queue()
results_store: Dict[str, Any] = {}
temp_dir = Path("temp_files")

# --- Background Worker ---
async def process_queue():
    """
    Asynchronously processes transcription tasks from the queue one by one.
    """
    logging.info("Queue processor started.")
    while True:
        try:
            chunk_id, file_path = await task_queue.get()
            
            try:
                logging.info(f"Starting transcription for {chunk_id}...")
                
                # Run the blocking transcribe function in a separate thread
                segments, _ = await asyncio.to_thread(
                    model.transcribe, str(file_path), beam_size=5, vad_filter=True
                )
                
                text = " ".join(s.text.strip() for s in segments)
                results_store[chunk_id] = {"status": "completed", "text": text}
                logging.info(f"Finished transcription for {chunk_id}.")

            except Exception as e:
                logging.error(f"Error processing {chunk_id}: {e}")
                results_store[chunk_id] = {"status": "error", "message": str(e)}
            finally:
                # Clean up the temp file
                if os.path.exists(file_path):
                    os.remove(file_path)
                task_queue.task_done()
        except asyncio.CancelledError:
            logging.info("Queue processor task cancelled.")
            break
        except Exception as e:
            logging.error(f"An error occurred in the main processing loop: {e}")
            await asyncio.sleep(1)

# --- Lifespan Events ---
@app.on_event("startup")
async def startup_event():
    """
    Loads the model and starts the background queue processor on application startup.
    """
    global model
    logging.info("Executing startup event...")

    # Synchronously load the model. This will block startup.
    try:
        model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
        logging.info("Model loaded successfully.")
    except Exception as e:
        logging.error(f"Failed to load model: {e}")
        raise
    
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(exist_ok=True)
    
    # Start the background queue processor
    asyncio.create_task(process_queue())
    logging.info("Startup event completed.")

# --- API Endpoints ---
@app.post("/enqueue_chunk", summary="Enqueue an audio chunk for transcription")
async def enqueue_chunk(file: UploadFile = File(..., description="The audio file to transcribe.")):
    """
    Accepts an audio file, saves it temporarily, and adds a transcription task to the queue.

    - **file**: The audio file (e.g., WAV, MP3) to be transcribed.

    Returns the accepted status and a unique ID for the transcription task.
    """
    chunk_id = str(uuid.uuid4())
    file_path = temp_dir / f"{chunk_id}.wav"
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    await task_queue.put((chunk_id, str(file_path)))
    results_store[chunk_id] = {"status": "queued"}
    
    return {"status": "accepted", "chunk_id": chunk_id}

@app.get("/get_result/{chunk_id}", summary="Get the result of a transcription task")
async def get_result(chunk_id: str):
    """
    Retrieves the status and result of a transcription task by its ID.

    - **chunk_id**: The unique ID of the task, returned by `/enqueue_chunk`.

    Possible statuses: `queued`, `completed`, `error`.
    The `text` field is only present if the status is `completed`.
    The `message` field is only present if the status is `error`.
    """
    result = results_store.get(chunk_id)
    if not result:
        raise HTTPException(status_code=404, detail="Chunk ID not found.")
    return result

@app.get("/health", summary="Check the health of the service")
async def health_check():
    """
    Checks if the service is running and the model is loaded.
    """
    return {"status": "ok" if model else "loading", "queue_size": task_queue.qsize()}
