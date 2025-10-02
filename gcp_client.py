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
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
PROXY_URL = os.environ.get("PROXY_URL")
if not PROXY_URL:
    raise ValueError("PROXY_URL environment variable not set. It should be the full URL of the proxy server.")

API_KEY = os.environ.get("PROXY_API_KEY")
if not API_KEY:
    raise ValueError("PROXY_API_KEY environment variable not set.")
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
        for i, s in enumerate(streams):
            stream_index = s['index']
            out_file = out_dir / f"{video_path.stem}_track_{stream_index}.wav"
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(video_path),
                "-map", f"0:a:{i}",
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

    # 3. Create a unique directory for this job's results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path("temp_results") / f"{file_path.stem}_{timestamp}"
    results_dir.mkdir(parents=True, exist_ok=True)
    print(f"Saving raw results to: {results_dir}")

    # 4. Process each track and save raw results
    for speaker, wav_path in extracted_tracks:
        print(f"\n--- Processing track: {speaker} ({wav_path.name}) ---")
        chunk_paths = chunk_audio_with_ffmpeg(wav_path)
        if not chunk_paths:
            print(f"No speech detected in track {speaker}.")
            continue

        track_jobs = {}
        max_concurrent_jobs = args.num_workers
        
        with tqdm(total=len(chunk_paths), desc=f"Transcribing {speaker}") as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent_jobs) as executor:
                
                chunk_iterator = iter(enumerate(chunk_paths))
                futures = set()
                
                for _ in range(max_concurrent_jobs):
                    try:
                        i, chunk_path = next(chunk_iterator)
                        future = executor.submit(upload_chunk, (chunk_path, i, session, args.num_workers))
                        futures.add(future)
                    except StopIteration:
                        break

                while futures:
                    done, futures = concurrent.futures.wait(
                        futures, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    
                    for future in done:
                        job_info = future.result()
                        if job_info:
                            track_jobs[job_info["chunk_id"]] = job_info
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
                                except requests.exceptions.RequestException:
                                    time.sleep(2)
                            
                            # Save the raw result to a file
                            if job_info["status"] == "completed":
                                result_data = job_info.get("result", {})
                                result_data['speaker'] = speaker # Add speaker info
                                result_filename = f"{speaker}_chunk_{job_info['order']:04d}.json"
                                with open(results_dir / result_filename, "w", encoding="utf-8") as f:
                                    json.dump(result_data, f, ensure_ascii=False, indent=2)

                        pbar.update(1)

                        try:
                            i, chunk_path = next(chunk_iterator)
                            new_future = executor.submit(upload_chunk, (chunk_path, i, session, args.num_workers))
                            futures.add(new_future)
                        except StopIteration:
                            pass
    
    print(f"\n[SUCCESS] Raw transcription data saved to {results_dir}")
    
    # 5. Post-process the results to create the final diarized transcript
    print("\nPost-processing results...")
    final_transcript = postprocess_results(results_dir)
    
    if final_transcript:
        output_filename = results_dir.parent / f"{results_dir.name}_diarized.json"
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(final_transcript, f, ensure_ascii=False, indent=2)
        
        print(f"\n[SUCCESS] Diarized transcript saved to {output_filename}")
    else:
        print("\nNo transcript generated.")

def postprocess_results(results_dir: Path):
    """
    Post-processes raw transcription results to create a diarized transcript.
    """
    # Group files by speaker and chunk number
    chunks_by_speaker = {}
    for json_file in results_dir.glob("*.json"):
        filename = json_file.stem
        parts = filename.rsplit('_chunk_', 1)
        if len(parts) == 2:
            speaker = parts[0]
            chunk_num = int(parts[1])
            if speaker not in chunks_by_speaker:
                chunks_by_speaker[speaker] = []
            chunks_by_speaker[speaker].append((chunk_num, json_file))
    
    # Sort chunks by number for each speaker
    for speaker in chunks_by_speaker:
        chunks_by_speaker[speaker].sort(key=lambda x: x[0])
    
    # Build timeline of all words with proper ordering
    all_words = []
    cumulative_time = 0.0
    
    # Interleave chunks from all speakers chronologically
    max_chunks = max(len(chunks) for chunks in chunks_by_speaker.values()) if chunks_by_speaker else 0
    
    for chunk_idx in range(max_chunks):
        for speaker in sorted(chunks_by_speaker.keys()):
            if chunk_idx < len(chunks_by_speaker[speaker]):
                _, json_file = chunks_by_speaker[speaker][chunk_idx]
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for segment in data.get('segments', []):
                        for word in segment.get('words', []):
                            all_words.append({
                                'word': word.get('word', ''),
                                'start': word.get('start', 0) + cumulative_time,
                                'end': word.get('end', 0) + cumulative_time,
                                'speaker': data.get('speaker', speaker)
                            })
                    # Update cumulative time based on last segment
                    segments = data.get('segments', [])
                    if segments:
                        last_segment = segments[-1]
                        cumulative_time += last_segment.get('end', 0)

    if not all_words:
        print("No words found in the result files.")
        return None

    # Sort all words by their adjusted timestamps
    all_words.sort(key=lambda x: x.get('start', 0))

    # Interleave phrases based on speaker changes and pauses
    final_transcript = []
    if all_words:
        current_speaker = all_words[0]['speaker']
        current_phrase = ""
        last_word_end = 0.0
        PHRASE_BREAK_THRESHOLD = 1.0

        for word_info in all_words:
            pause_duration = word_info.get('start', 0) - last_word_end
            
            if word_info['speaker'] != current_speaker or (pause_duration >= PHRASE_BREAK_THRESHOLD and last_word_end > 0):
                if current_phrase:
                    final_transcript.append({"speaker": current_speaker, "text": current_phrase.strip()})
                
                current_speaker = word_info['speaker']
                current_phrase = word_info.get('word', '')
            else:
                current_phrase += " " + word_info.get('word', '')

            last_word_end = word_info.get('end', 0)
        
        if current_phrase:
            final_transcript.append({"speaker": current_speaker, "text": current_phrase.strip()})
    
    return final_transcript

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
