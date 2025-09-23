import os
import subprocess
from pathlib import Path
import json
from datetime import datetime
import time
import requests
from tqdm import tqdm
import torch
import torchaudio
import warnings

# --- Configuration ---
WORKER_URL = "http://localhost:8000"
AUDIO_VIDEO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg",
                    ".mp4", ".mkv", ".mov", ".m4v", ".webm"}
DEFAULT_VIDEO_DIR = Path(r"C:\Users\mosha\Videos")
CHUNK_TEMP_DIR = Path("temp_audio_chunks")
MODEL_CACHE_DIR = Path("./model_cache")

# --- Suppress UserWarnings from torchaudio ---
warnings.filterwarnings("ignore", category=UserWarning, module='torchaudio')

# --- VAD Setup ---
try:
    torch.hub.set_dir(str(MODEL_CACHE_DIR))
    vad_model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False)
    (get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = utils
except Exception as e:
    print(f"Could not load Silero VAD model. Error: {e}")
    vad_model = None

# --- Core Functions ---

def extract_wav(input_path: Path, sr: int = 16000) -> Path:
    """Extracts a 16kHz mono WAV file from any audio/video file using ffmpeg."""
    out_wav = CHUNK_TEMP_DIR / (input_path.stem + "_16k_mono.wav")
    if out_wav.exists() and out_wav.stat().st_size > 0:
        return out_wav
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path),
        "-vn", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(sr),
        str(out_wav)
    ]
    subprocess.run(cmd, check=True)
    return out_wav

def pick_file(directory: Path) -> Path:
    """Displays the 10 most recently modified files and prompts the user to pick one."""
    files = [f for f in directory.iterdir() if f.suffix.lower() in AUDIO_VIDEO_EXTS]
    if not files:
        print(f"No audio/video files found in {directory}")
        exit(1)
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    last10 = files[:10]
    print("Last 10 modified files:")
    for i, f in enumerate(last10, 1):
        ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{i}. {f.name} (modified: {ts})")
    while True:
        try:
            choice = int(input("Select file number: "))
            if 1 <= choice <= len(last10):
                return last10[choice - 1]
        except ValueError:
            print("Please enter a number.")

def chunk_audio_with_vad(wav_path: Path, sr: int = 16000) -> list[Path]:
    """Splits a WAV file into smaller chunks based on voice activity detection (VAD)."""
    if not vad_model:
        return [wav_path]
    wav = read_audio(str(wav_path), sampling_rate=sr)
    speech_timestamps = get_speech_timestamps(wav, vad_model, sampling_rate=sr, min_silence_duration_ms=400, speech_pad_ms=200)
    chunk_paths = []
    for i, ts in enumerate(speech_timestamps):
        chunk_file = CHUNK_TEMP_DIR / f"{wav_path.stem}_chunk_{i:04d}.wav"
        save_audio(chunk_file, collect_chunks([ts], wav), sampling_rate=sr)
        chunk_paths.append(chunk_file)
    print(f"Split audio into {len(chunk_paths)} chunks.")
    return chunk_paths

def main():
    CHUNK_TEMP_DIR.mkdir(exist_ok=True)
    MODEL_CACHE_DIR.mkdir(exist_ok=True)
    
    # 1. Check if the worker service is ready.
    # The server might take a while to start up as it loads the model.
    try:
        print("Connecting to worker... (this may take up to 60s for the model to load)")
        response = requests.get(f"{WORKER_URL}/health", timeout=60)
        response.raise_for_status()
        print(f"Worker is healthy: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"Could not connect to the worker at {WORKER_URL}. Is it running?")
        print(f"Error: {e}")
        return

    # 2. Pre-process the audio file.
    file_path = pick_file(DEFAULT_VIDEO_DIR)
    wav_path = extract_wav(file_path)
    chunk_paths = chunk_audio_with_vad(wav_path)
    
    if not chunk_paths:
        print("No speech detected.")
        return

    # 3. Enqueue all audio chunks for transcription.
    chunk_jobs = {}
    print("Uploading chunks to worker...")
    for chunk_path in tqdm(chunk_paths, desc="Enqueueing"):
        try:
            with open(chunk_path, "rb") as f:
                files = {"file": (chunk_path.name, f, "audio/wav")}
                response = requests.post(f"{WORKER_URL}/enqueue_chunk", files=files, timeout=30)
                response.raise_for_status()
                result = response.json()
                chunk_jobs[result["chunk_id"]] = {"path": chunk_path, "status": "queued", "order": len(chunk_jobs)}
        except requests.exceptions.RequestException as e:
            print(f"\nError uploading chunk {chunk_path.name}: {e}")
            continue
    
    # 4. Poll for results until all chunks are processed.
    print("Waiting for results...")
    completed_jobs = 0
    with tqdm(total=len(chunk_jobs), desc="Transcribing") as pbar:
        while completed_jobs < len(chunk_jobs):
            for chunk_id, job_info in chunk_jobs.items():
                if job_info["status"] == "queued":
                    try:
                        response = requests.get(f"{WORKER_URL}/get_result/{chunk_id}", timeout=10)
                        response.raise_for_status()
                        result = response.json()
                        
                        if result["status"] == "completed":
                            job_info["status"] = "completed"
                            job_info["text"] = result["text"]
                            completed_jobs += 1
                            pbar.update(1)
                        elif result["status"] == "error":
                            job_info["status"] = "error"
                            job_info["text"] = f"ERROR: {result.get('message', 'Unknown')}"
                            completed_jobs += 1
                            pbar.update(1)
                            
                    except requests.exceptions.RequestException as e:
                        print(f"\nError polling for chunk {chunk_id}: {e}. Retrying...")
                        time.sleep(2)
            time.sleep(1)

    # 5. Assemble and save the final transcript.
    print("Assembling final transcript...")
    sorted_chunks = sorted(chunk_jobs.values(), key=lambda x: x["order"])
    full_text = " ".join(chunk["text"] for chunk in sorted_chunks if "text" in chunk).strip()

    base = file_path.with_suffix("")
    txt_path = base.with_name(base.name + "_transcription.txt")
    json_path = base.with_name(base.name + "_transcription.json")

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(full_text + "\n")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"text": full_text}, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Transcription complete!")
    print(f"[out] TXT:  {txt_path}")
    print(f"[out] JSON: {json_path}")

if __name__ == "__main__":
    main()
