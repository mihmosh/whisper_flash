# Развертывание в Google Cloud Platform (Slim версия)

Этот документ описывает шаги для развертывания slim версии сервиса транскрипции в GCP с использованием Cloud Run и GPU. Эта версия использует runtime образ PyTorch вместо development версии, что значительно уменьшает размер Docker образа.

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

## 3. Сборка и публикация slim Docker-образа

1.  **Создайте репозиторий в Artifact Registry (если еще не создан):**
    ```bash
    gcloud artifacts repositories create transcriber-repo --repository-format=docker --location=europe-west4
    ```

2.  **Настройте Docker для аутентификации (если еще не настроено):**
    ```bash
    gcloud auth configure-docker europe-west4-docker.pkg.dev
    ```

3.  **Соберите и отправьте slim образ с помощью Cloud Build:**
    *   Создайте файл `cloudbuild_slim.yaml` в корне проекта:
        ```yaml
        steps:
        - name: 'gcr.io/cloud-builders/docker'
          entrypoint: 'bash'
          args: ['-c', 'docker pull europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber-slim:latest || exit 0']
        - name: 'gcr.io/cloud-builders/docker'
          args:
          - 'build'
          - '-t'
          - 'europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber-slim:latest'
          - '-f'
          - './worker/Dockerfile.slim'
          - './worker'
          - '--cache-from'
          - 'europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber-slim:latest'
        images:
        - 'europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber-slim:latest'
        ```
    *   Запустите сборку:
        ```bash
        gcloud builds submit --config cloudbuild_slim.yaml .
        ```

## 4. Развертывание slim версии в Cloud Run

Выполните следующие команды для развертывания четырех экземпляров сервиса с использованием slim образа:

```bash
gcloud run deploy transcriber-slim-1 \
  --image europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber-slim:latest \
  --region europe-west4 \
  --gpu type=nvidia-l4,count=1 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --allow-unauthenticated

gcloud run deploy transcriber-slim-2 \
  --image europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber-slim:latest \
  --region europe-west4 \
  --gpu type=nvidia-l4,count=1 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --allow-unauthenticated

gcloud run deploy transcriber-slim-3 \
  --image europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber-slim:latest \
  --region europe-west4 \
  --gpu type=nvidia-l4,count=1 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --allow-unauthenticated

gcloud run deploy transcriber-slim-4 \
  --image europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber-slim:latest \
  --region europe-west4 \
  --gpu type=nvidia-l4,count=1 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --allow-unauthenticated
```

## 5. Настройка клиента

После развертывания slim версии вы получите URL для каждого сервиса. Их нужно будет вставить в `local_client.py` в список `WORKER_URLS`, заменив URL сервисов из обычной версии.

## Преимущества slim версии

- **Значительно меньший размер образа**: Runtime версия PyTorch не включает в себя инструменты разработки и лишние библиотеки, что уменьшает размер образа с 28ГБ до примерно 4-6ГБ.
- **Более быстрая сборка и деплой**: Меньший образ быстрее собирается, загружается и запускается.
- **Снижение затрат**: Меньший образ занимает меньше места в Artifact Registry и может снижать затраты на передачу данных.

## Локальное тестирование slim версии

Для локального тестирования slim версии используйте docker-compose:

```bash
docker-compose up worker-slim
```

Это запустит сервис на порту 8081, в то время как оригинальный worker сервис будет доступен на порту 8080.

## Ограничения slim версии

- **Нет инструментов разработки**: Эта версия не подходит для разработки, отладки или компиляции кода внутри контейнера.
- **Нельзя использовать для локальной разработки**: Для локальной разработки по-прежнему следует использовать оригинальный Dockerfile.