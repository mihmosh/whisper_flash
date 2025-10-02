# Deployment to Google Cloud Platform

This document describes the steps to deploy the transcription service to GCP using Cloud Run with GPUs.

## 1. Prerequisites

- `gcloud` CLI installed.
- `docker` installed.
- A Google Cloud project with a billing account attached.

## 2. Project Setup

1.  **Log in to your Google Cloud account:**
    ```bash
    gcloud auth login
    ```

2.  **Set your default project:**
    ```bash
    gcloud config set project [YOUR_PROJECT_ID]
    ```

3.  **Enable the required APIs:**
    ```bash
    gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
    ```

## 3. Build and Publish the Docker Image

1.  **Create a repository in Artifact Registry:**
    ```bash
    gcloud artifacts repositories create transcriber-repo --repository-format=docker --location=europe-west4
    ```

2.  **Configure Docker for authentication:**
    ```bash
    gcloud auth configure-docker europe-west4-docker.pkg.dev
    ```

3.  **Build and push the image using Cloud Build:**
    *   Create a `cloudbuild.yaml` file in the project root:
        ```yaml
        steps:
        - name: 'gcr.io/cloud-builders/docker'
          entrypoint: 'bash'
          args: ['-c', 'docker pull europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest || exit 0']
        - name: 'gcr.io/cloud-builders/docker'
          args:
          - 'build'
          - '-t'
          - 'europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest'
          - './worker'
          - '--cache-from'
          - 'europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest'
        images:
        - 'europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest'
        ```
    *   Start the build:
        ```bash
        gcloud builds submit --config cloudbuild.yaml .
        ```

## 4. Deploy to Cloud Run

Execute the following commands to deploy four instances of the service:

```bash
gcloud run deploy transcriber-1 \
  --image europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest \
  --region europe-west4 \
  --gpu type=nvidia-l4,count=1 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --allow-unauthenticated

gcloud run deploy transcriber-2 \
  --image europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest \
  --region europe-west4 \
  --gpu type=nvidia-l4,count=1 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --allow-unauthenticated

gcloud run deploy transcriber-3 \
  --image europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest \
  --region europe-west4 \
  --gpu type=nvidia-l4,count=1 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --allow-unauthenticated

gcloud run deploy transcriber-4 \
  --image europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest \
  --region europe-west4 \
  --gpu type=nvidia-l4,count=1 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --allow-unauthenticated
```

## 5. Client Configuration

After deployment, you will get a URL for each service. You will need to insert these into the `WORKER_URLS` list in `gcp_client.py` or the proxy configuration.
