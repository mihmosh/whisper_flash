import requests
import time

WORKER_URL = "http://localhost:8000"

def main():
    # Check health
    try:
        response = requests.get(f"{WORKER_URL}/health", timeout=10)
        response.raise_for_status()
        print(f"Health check OK: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"Health check FAILED: {e}")
        return

    # Create a dummy file to upload
    dummy_file_path = "test.tmp"
    with open(dummy_file_path, "w") as f:
        f.write("test")

    # Upload the file
    task_id = None
    try:
        with open(dummy_file_path, "rb") as f:
            files = {"file": ("test.tmp", f, "application/octet-stream")}
            print("Uploading dummy file...")
            response = requests.post(f"{WORKER_URL}/upload", files=files, timeout=30)
            response.raise_for_status()
            result = response.json()
            task_id = result.get("task_id")
            if task_id:
                print(f"Upload OK. Task ID: {task_id}")
            else:
                print(f"Upload FAILED: No task_id in response.")
                return
    except requests.exceptions.RequestException as e:
        print(f"Upload FAILED: {e}")
        return
    finally:
        if os.path.exists(dummy_file_path):
            os.remove(dummy_file_path)

    # Get the result
    if task_id:
        try:
            print(f"Polling for result for task {task_id}...")
            time.sleep(1) # Give the server a moment
            response = requests.get(f"{WORKER_URL}/result/{task_id}", timeout=10)
            response.raise_for_status()
            result = response.json()
            print(f"Get result OK: {result}")
            if result.get("status") == "completed" and result.get("text"):
                print("TEST PASSED!")
            else:
                print("TEST FAILED: Invalid result content.")
        except requests.exceptions.RequestException as e:
            print(f"Get result FAILED: {e}")

if __name__ == "__main__":
    import os
    main()
