import os
import subprocess
from pathlib import Path
import json
from datetime import datetime
import time
import requests
from tqdm import tqdm
import torch
import concurrent.futures
import torchaudio
import warnings
import argparse

# --- Configuration ---
PROXY_URL = "http://34.90.198.59"
API_KEY = "your-super-secret-api-key" # This must match the key in the proxy_server.py
AUDIO_VIDEO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg",
                    ".mp4", ".mkv", ".mov", ".m4v", ".webm"}
DEFAULT_VIDEO_DIR = Path(r"C:\Users\mosha\Videos")
CHUNK_TEMP_DIR = Path("temp_audio_chunks")
MODEL_CACHE_DIR = Path("./model_cache")

# --- Suppress UserWarnings from torchaudio ---
warnings.filterwarnings("ignore", category=UserWarning, module='torchaudio')

# --- Core Functions ---

def get_audio_streams(path: Path):
    """
    Analyzes the audio streams in a media file using ffprobe.
    Returns a list of stream info dictionaries.
    """
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index,channels",
        "-of", "json", str(path)
    ]
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
        return json.loads(out.stdout)["streams"]
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        print(f"Error analyzing audio streams for {path}: {e}")
        return []

def extract_tracks(video_path: Path, out_dir: Path) -> list[tuple[str, Path]]:
    """
    Extracts audio tracks from a video file based on stream analysis.
    - If one stereo stream -> extracts one mono WAV.
    - If multiple mono streams -> extracts each into a separate WAV.
    Returns a list of tuples: (track_name, wav_path).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    streams = get_audio_streams(video_path)
    outputs = []

    if not streams:
        print(f"No audio streams found in {video_path}. Aborting.")
        return []

    # Case 1: Single stream with more than 1 channel (e.g., stereo) -> mix down to mono
    if len(streams) == 1 and streams[0]["channels"] > 1:
        print(f"Detected a single {streams[0]['channels']}-channel stream. Converting to mono.")
        out_file = out_dir / f"{video_path.stem}_mono.wav"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
            str(out_file)
        ]
        subprocess.run(cmd, check=True)
        outputs.append(("mixed_mono", out_file))

    # Case 2: Multiple mono streams -> extract each one separately
    else:
        print(f"Detected {len(streams)} separate audio streams. Extracting each.")
        for s in streams:
            stream_index = s['index']
            out_file = out_dir / f"{video_path.stem}_track_{stream_index}.wav"
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(video_path),
                "-map", f"0:a:{stream_index}",
                "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le",
                str(out_file)
            ]
            subprocess.run(cmd, check=True)
            outputs.append((f"track_{stream_index}", out_file))

    return outputs

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

def chunk_audio_with_ffmpeg(wav_path: Path, min_silence_len=2.5, silence_thresh="-25dB") -> list[Path]:
    """
    Splits a WAV file into chunks using ffmpeg's silencedetect filter.
    This is much faster than model-based VAD.
    """
    print("Chunking audio with ffmpeg silencedetect...")
    
    # 1. Detect silence
    silence_cmd = [
        "ffmpeg", "-y", "-hide_banner",
        "-i", str(wav_path),
        "-af", f"silencedetect=n={silence_thresh}:d={min_silence_len}",
        "-f", "null", "-"
    ]
    
    result = subprocess.run(silence_cmd, capture_output=True, text=True)
    stderr = result.stderr
    
    # 2. Parse timestamps
    import re
    silence_starts = re.findall(r"silence_start: (\d+\.?\d*)", stderr)
    silence_ends = re.findall(r"silence_end: (\d+\.?\d*)", stderr)
    
    if not silence_starts or not silence_ends:
        print("No silence detected, using the whole file as one chunk.")
        return [wav_path]

    # Ensure we have pairs of start/end times
    if len(silence_starts) > len(silence_ends):
        silence_starts = silence_starts[:len(silence_ends)]
    elif len(silence_ends) > len(silence_starts):
        silence_ends = silence_ends[:len(silence_starts)]

    # 3. Create speech segments from the inverse of silence
    chunk_paths = []
    last_end = 0.0
    
    print("Splitting audio into chunks...")
    for i, (start, end) in enumerate(tqdm(zip(silence_starts, silence_ends), total=len(silence_starts), desc="Chunking")):
        speech_start = float(last_end)
        speech_end = float(start)
        duration = speech_end - speech_start
        
        if duration > 0.5:  # Only save chunks longer than 0.5s
            chunk_file = CHUNK_TEMP_DIR / f"{wav_path.stem}_chunk_{i:04d}.wav"
            split_cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(wav_path),
                "-ss", str(speech_start),
                "-to", str(speech_end),
                "-c", "copy",
                str(chunk_file)
            ]
            subprocess.run(split_cmd, check=True)
            chunk_paths.append(chunk_file)
        
        last_end = end

    print(f"Split audio into {len(chunk_paths)} chunks.")
    return chunk_paths

def get_authed_session():
    """Creates a session with the proxy API key."""
    session = requests.Session()
    session.headers.update({"X-API-Key": API_KEY})
    return session

def upload_chunk(args):
    """Uploads a single chunk to a worker and returns the job info."""
    chunk_path, i, session, num_workers = args
    worker_id = i % num_workers
    try:
        with open(chunk_path, "rb") as f:
            files = {"file": (chunk_path.name, f, "audio/wav")}
            enqueue_url = f"{PROXY_URL}/{worker_id}/enqueue_chunk"
            response = session.post(enqueue_url, files=files, timeout=30)
            response.raise_for_status()
            result = response.json()
            return {
                "chunk_id": result["chunk_id"],
                "path": chunk_path,
                "status": "queued",
                "order": i,
                "worker_id": worker_id
            }
    except requests.exceptions.RequestException as e:
        print(f"\nError uploading chunk {chunk_path.name} to worker {worker_id}: {e}")
        return None

def health_check_workers(session, num_workers):
    """Sends a health check to all workers asynchronously to 'wake them up'."""
    print(f"Pinging {num_workers} workers to wake them up...")
    
    def check_worker(worker_id):
        try:
            health_url = f"{PROXY_URL}/{worker_id}/health"
            response = session.get(health_url, timeout=20)
            response.raise_for_status()
            return True, worker_id
        except requests.exceptions.RequestException:
            return False, worker_id

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(check_worker, i) for i in range(num_workers)]
        
        success_count = 0
        for future in concurrent.futures.as_completed(futures):
            success, worker_id = future.result()
            if success:
                success_count += 1
            else:
                print(f"Warning: Worker {worker_id} did not respond to health check.")
    
    print(f"{success_count}/{num_workers} workers responded successfully.")
    if success_count == 0:
        print("No workers are available. Aborting.")
        return False
    return True

def main(args):
    CHUNK_TEMP_DIR.mkdir(exist_ok=True)
    MODEL_CACHE_DIR.mkdir(exist_ok=True)
    session = get_authed_session()

    # 1. Asynchronously ping all workers to wake them up.
    if not health_check_workers(session, args.num_workers):
        return

    # 2. Pick file and extract audio tracks while workers are warming up.
    file_path = pick_file(DEFAULT_VIDEO_DIR)
    extracted_tracks = extract_tracks(file_path, CHUNK_TEMP_DIR)

    if not extracted_tracks:
        print("No audio tracks were extracted. Exiting.")
        return

    # 3. Process each track
    all_results = []
    for speaker, wav_path in extracted_tracks:
        print(f"\n--- Processing track: {speaker} ({wav_path.name}) ---")
        chunk_paths = chunk_audio_with_ffmpeg(wav_path)
        if not chunk_paths:
            print(f"No speech detected in track {speaker}.")
            continue

        # Process chunks for the current track
        track_jobs = {}
        max_concurrent_jobs = args.num_workers
        
        with tqdm(total=len(chunk_paths), desc=f"Transcribing {speaker}") as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent_jobs) as executor:
                
                # Create an iterator for the chunks to be submitted
                chunk_iterator = iter(enumerate(chunk_paths))
                
                # Keep track of the futures that are currently running
                futures = set()
                
                # Prime the queue with initial jobs
                for _ in range(max_concurrent_jobs):
                    try:
                        i, chunk_path = next(chunk_iterator)
                        future = executor.submit(upload_chunk, (chunk_path, i, session, args.num_workers))
                        futures.add(future)
                    except StopIteration:
                        break # No more chunks

                # Process futures as they complete, and submit new ones
                while futures:
                    done, futures = concurrent.futures.wait(
                        futures, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    
                    for future in done:
                        # Process the completed job
                        job_info = future.result()
                        if job_info:
                            track_jobs[job_info["chunk_id"]] = job_info
                            # Poll for result
                            while job_info["status"] not in ["completed", "error"]:
                                try:
                                    worker_id = job_info["worker_id"]
                                    result_url = f"{PROXY_URL}/{worker_id}/get_result/{job_info['chunk_id']}"
                                    response = session.get(result_url, timeout=10)
                                    response.raise_for_status()
                                    result = response.json()
                                    job_info.update(result)
                                    if result["status"] in ["completed", "error"]:
                                        break
                                    time.sleep(1)
                                except requests.exceptions.RequestException as e:
                                    print(f"\nError polling for chunk {job_info['chunk_id']}: {e}. Retrying...")
                                    time.sleep(2)
                        
                        pbar.update(1)

                        # Try to submit a new job
                        try:
                            i, chunk_path = next(chunk_iterator)
                            new_future = executor.submit(upload_chunk, (chunk_path, i, session, args.num_workers))
                            futures.add(new_future)
                        except StopIteration:
                            # No more chunks to submit, the loop will drain the remaining futures
                            pass

        # Assemble text for the current track using word timestamps for formatting
        sorted_chunks = sorted(track_jobs.values(), key=lambda x: x["order"])
        
        # Consolidate all word segments from all chunks into a single list
        all_words = []
        for chunk in sorted_chunks:
            if chunk["status"] == "completed":
                # The result from the worker should contain a 'words' list
                # Example: {"text": "...", "words": [{"word": "hello", "start": 0.1, "end": 0.5}, ...]}
                words = chunk.get("result", {}).get("words")
                if words:
                    all_words.extend(words)

        # Reconstruct the transcript with intelligent formatting based on pauses
        track_text = ""
        if all_words:
            # Define pause thresholds (in seconds)
            NEW_PARAGRAPH_THRESHOLD = 1.5
            NEW_LINE_THRESHOLD = 0.7

            last_word_end = 0.0
            for word_info in all_words:
                pause_duration = word_info['start'] - last_word_end
                
                if last_word_end > 0: # Don't add separator before the first word
                    if pause_duration >= NEW_PARAGRAPH_THRESHOLD:
                        track_text += "\n\n"
                    elif pause_duration >= NEW_LINE_THRESHOLD:
                        track_text += "\n"
                    else:
                        track_text += " "
                
                track_text += word_info['word']
                last_word_end = word_info['end']
        
        all_results.append({"speaker": speaker, "text": track_text.strip()})

    # 4. Save final diarized transcript
    if not all_results:
        print("\nNo text was transcribed.")
        return
        
    base = file_path.with_suffix("")
    json_path = base.with_name(base.name + "_transcription_diarized.json")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Transcription complete!")
    print(f"[out] Diarized JSON: {json_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Asynchronous transcription client.")
    parser.add_argument(
        "-n", "--num-workers", 
        type=int, 
        default=4, 
        help="Number of parallel workers to use for uploading chunks."
    )
    args = parser.parse_args()
    main(args)
