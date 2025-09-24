from faster_whisper import WhisperModel
import torch

# --- Configuration ---
MODEL_SIZE = "large-v3"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = "float16" if DEVICE == "cuda" else "int8"

def main():
    """
    Downloads and caches the faster-whisper model.
    This script is intended to be run during the Docker build process.
    """
    print(f"Downloading and caching model '{MODEL_SIZE}' for device '{DEVICE}'...")
    try:
        _ = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
        print("Model downloaded and cached successfully.")
    except Exception as e:
        print(f"Failed to download model: {e}")
        # Exit with a non-zero code to fail the Docker build if download fails
        exit(1)

if __name__ == "__main__":
    main()
