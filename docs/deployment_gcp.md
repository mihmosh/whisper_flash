# Развертывание в Google Cloud Platform

Этот документ описывает шаги для развертывания сервиса транскрипции в GCP с использованием Cloud Run и GPU.

## 1. Предварительные требования

- Установленный `gcloud` CLI.
- Установленный `docker`.
- Проект в Google Cloud с привязанным платежным аккаунтом.

## 2. Настройка проекта

1.  **Войдите в свой аккаунт Google Cloud:**
    ```bash
    gcloud auth login
    ```

2.  **Установите ваш проект по умолчанию:**
    ```bash
    gcloud config set project [YOUR_PROJECT_ID]
    ```

3.  **Включите необходимые API:**
    ```bash
    gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
    ```

## 3. Сборка и публикация Docker-образа

1.  **Создайте репозиторий в Artifact Registry:**
    ```bash
    gcloud artifacts repositories create transcriber-repo --repository-format=docker --location=europe-west4
    ```

2.  **Настройте Docker для аутентификации:**
    ```bash
    gcloud auth configure-docker europe-west4-docker.pkg.dev
    ```

3.  **Соберите и отправьте образ с помощью Cloud Build:**
    *   Создайте файл `cloudbuild.yaml` в корне проекта:
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
    *   Запустите сборку:
        ```bash
        gcloud builds submit --config cloudbuild.yaml .
        ```

## 4. Развертывание в Cloud Run

Выполните следующие команды для развертывания четырех экземпляров сервиса:

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

## 5. Настройка клиента

После развертывания вы получите URL для каждого сервиса. Их нужно будет вставить в `local_client.py` в список `WORKER_URLS`.
