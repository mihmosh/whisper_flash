#!/bin/bash
# Update and install dependencies, including venv
apt-get update
apt-get install -y python3-pip python3-venv

# Create a directory for the app
mkdir -p /opt/proxy
cd /opt/proxy

# Create a virtual environment
python3 -m venv venv

# Activate venv and install Python libraries
source venv/bin/activate
pip install Flask requests google-auth

# Create the proxy server application file
cat <<'EOF' > proxy_server.py
from flask import Flask, request, Response
import requests
import google.auth
import google.auth.transport.requests
import google.oauth2.id_token

app = Flask(__name__)

# --- Configuration ---
# The internal URLs of the Cloud Run services, in order.
TARGET_URLS = [
    "https://transcriber-gpu-worker-811229424702.europe-west4.run.app",
    "https://transcriber-gpu-worker-2-811229424702.europe-west4.run.app",
    "https://transcriber-gpu-worker-3-811229424702.europe-west4.run.app",
    "https://transcriber-gpu-worker-4-811229424702.europe-west4.run.app",
]
# A simple, static API key for clients to use
API_KEY = "your-super-secret-api-key" # Replace with a real secret

def get_gcp_token(target_url):
    """Gets a scoped identity token for a specific Cloud Run service."""
    try:
        auth_req = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, target_url)
        return token
    except Exception as e:
        print(f"Error getting GCP token for {target_url}: {e}")
        return None

@app.route('/<int:worker_id>/<path:path>', methods=['GET', 'POST'])
def proxy(worker_id, path):
    # 1. Check for client API key
    client_api_key = request.headers.get('X-API-Key')
    if client_api_key != API_KEY:
        return "Unauthorized", 401

    # 2. Validate worker_id and select the target URL
    if not (0 <= worker_id < len(TARGET_URLS)):
        return "Invalid worker ID", 400
    target_url = TARGET_URLS[worker_id]

    # 3. Get GCP identity token for the selected worker
    gcp_token = get_gcp_token(target_url)
    if not gcp_token:
        return "Could not authenticate to GCP", 500

    # 4. Prepare the request to be forwarded
    headers = {
        'Authorization': f'Bearer {gcp_token}',
        'Content-Type': request.content_type,
    }
    
    # 5. Forward the request
    try:
        resp = requests.request(
            method=request.method,
            url=f"{target_url}/{path}",
            headers=headers,
            data=request.get_data(),
            stream=True
        )
        # 6. Stream the response back to the client
        return Response(resp.iter_content(chunk_size=1024), status=resp.status_code, content_type=resp.headers['Content-Type'])
    except Exception as e:
        return f"Error during request forwarding to {target_url}: {e}", 502

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
EOF

# Run the proxy server using the python from the venv
nohup venv/bin/python proxy_server.py &
