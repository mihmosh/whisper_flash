import time
import threading
from flask import Flask, request, Response
import requests
import google.auth
import google.auth.transport.requests
import google.oauth2.id_token

app = Flask(__name__)

# --- Configuration ---
TARGET_URLS = [
    "https://transcriber-gpu-worker-811229424702.europe-west4.run.app",
    "https://transcriber-gpu-worker-2-811229424702.europe-west4.run.app",
    "https://transcriber-gpu-worker-3-811229424702.europe-west4.run.app",
    "https://transcriber-gpu-worker-4-811229424702.europe-west4.run.app",
]
API_KEY = "your-super-secret-api-key"

# --- Caching and Session Setup ---
TOKEN_TTL = 300  # Cache tokens for 5 minutes
_token_cache = {}
_lock = threading.Lock()

sess = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=200, pool_maxsize=200)
sess.mount("https://", adapter)

def get_gcp_token(target_url):
    """Gets a cached or new identity token for a specific Cloud Run service."""
    with _lock:
        hit = _token_cache.get(target_url)
        if hit and hit["exp"] > time.time():
            return hit["tok"]
    
    try:
        auth_req = google.auth.transport.requests.Request()
        tok = google.oauth2.id_token.fetch_id_token(auth_req, target_url)
        with _lock:
            _token_cache[target_url] = {"tok": tok, "exp": time.time() + TOKEN_TTL}
        return tok
    except Exception as e:
        print(f"Error getting GCP token for {target_url}: {e}")
        return None

@app.route('/<int:worker_id>/<path:path>', methods=['GET', 'POST'])
def proxy(worker_id, path):
    if request.headers.get('X-API-Key') != API_KEY:
        return "Unauthorized", 401

    if not (0 <= worker_id < len(TARGET_URLS)):
        return "Invalid worker ID", 400
    target_url = TARGET_URLS[worker_id]

    gcp_token = get_gcp_token(target_url)
    if not gcp_token:
        return "Could not authenticate to GCP", 500

    headers = {
        'Authorization': f'Bearer {gcp_token}',
        'Content-Type': request.content_type,
    }
    
    try:
        resp = sess.request(
            method=request.method,
            url=f"{target_url}/{path}",
            headers=headers,
            data=request.get_data(),
            stream=True,
            timeout=300 # Add a timeout
        )
        return Response(resp.iter_content(chunk_size=1024), status=resp.status_code, content_type=resp.headers['Content-Type'])
    except Exception as e:
        return f"Error during request forwarding to {target_url}: {e}", 502

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
