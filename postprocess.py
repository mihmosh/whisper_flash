import json
from pathlib import Path
import argparse

def process_results(results_dir: Path):
    """
    Loads raw transcription results from a directory, processes them to create a
    diarized transcript, and saves the final output.
    """
    if not results_dir.is_dir():
        print(f"Error: Directory not found at '{results_dir}'")
        return

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
    # Get max chunk count across all speakers
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
        return

    # Now sort all words by their adjusted timestamps
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

    # Save the final transcript
    output_filename = results_dir.parent / f"{results_dir.name}_diarized.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(final_transcript, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Diarized transcript saved to {output_filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Post-process raw transcription results.")
    parser.add_argument(
        "results_dir", 
        type=Path,
        nargs='?',
        help="The directory containing the raw JSON result files. If not provided, uses the most recent directory in temp_results."
    )
    args = parser.parse_args()
    
    # If no directory provided, find the most recent one
    if args.results_dir is None:
        temp_results = Path("temp_results")
        if not temp_results.exists():
            print("Error: temp_results directory not found.")
            exit(1)
        
        subdirs = [d for d in temp_results.iterdir() if d.is_dir()]
        if not subdirs:
            print("Error: No result directories found in temp_results.")
            exit(1)
        
        # Get the most recently modified directory
        args.results_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
        print(f"Using most recent results directory: {args.results_dir}")
    
    process_results(args.results_dir)
