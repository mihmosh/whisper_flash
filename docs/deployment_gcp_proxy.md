# Развертывание в GCP с использованием VM-прокси (для защищенных сред)

Этот документ описывает шаги для развертывания сервиса транскрипции в GCP в средах с повышенными требованиями к безопасности, где прямой доступ к Cloud Run и создание ключей сервисных аккаунтов запрещены.

Мы используем архитектуру с VM-прокси, которая выступает в роли безопасного шлюза между клиентом и приватным сервисом Cloud Run.

## Архитектура

1.  **Клиент (`gcp_client.py`):** Локальный скрипт, который обращается к публичному IP-адресу VM-прокси.
2.  **VM-прокси (Compute Engine):** Небольшая, постоянно работающая виртуальная машина. Принимает запросы от клиента, аутентифицируется в GCP с помощью своего сервисного аккаунта и перенаправляет запрос в Cloud Run.
3.  **Сервис (`transcriber-gpu-worker`):** Приватный сервис Cloud Run с GPU, который принимает трафик только от VM-прокси.

---

## Шаг 1: Развертывание приватного сервиса Cloud Run

Используйте эту команду, чтобы развернуть сервис. Обратите внимание на правильные флаги `--gpu` и `--gpu-type`.

```bash
gcloud run deploy transcriber-gpu-worker \
  --image=europe-west4-docker.pkg.dev/[YOUR_PROJECT_ID]/transcriber-repo/transcriber:latest \
  --region=europe-west4 \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --cpu=4 \
  --memory=16Gi \
  --max-instances=1 \
  --ingress=internal
```
*При развертывании `gcloud` может спросить про "unauthenticated invocations" - отвечайте `y`. Он также может пожаловаться на отсутствие квот для "zonal redundancy" - согласитесь на развертывание без нее (`y`).*

---

## Шаг 2: Создание VM-прокси

Создаем небольшую виртуальную машину, которая будет работать как наш прокси.

```bash
gcloud compute instances create transcriber-proxy-vm \
  --zone=europe-west4-a \
  --machine-type=e2-micro \
  --tags=proxy-server
```

---

## Шаг 3: Настройка прав доступа для VM

Даем сервисному аккаунту нашей VM право вызывать сервис Cloud Run. Замените `[PROJECT_NUMBER]` на номер вашего проекта.

```bash
gcloud run services add-iam-policy-binding transcriber-gpu-worker \
  --region=europe-west4 \
  --member="serviceAccount:[PROJECT_NUMBER]-compute@developer.gserviceaccount.com" \
  --role="roles/run.invoker"
```

---

## Шаг 4: Настройка Firewall

Открываем порт 80 для нашей VM, чтобы принимать HTTP-трафик.

```bash
gcloud compute firewall-rules create allow-proxy-http \
  --direction=INGRESS \
  --priority=1000 \
  --network=default \
  --action=ALLOW \
  --rules=tcp:80 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=proxy-server
```

---

## Шаг 5: Код и настройка прокси-сервера

Мы не будем настраивать сервер вручную. Вместо этого, мы используем `startup-script`, который автоматически настроит VM при создании.

**Код прокси-сервера (`proxy_server.py`):**
```python
from flask import Flask, request, Response
import requests
import google.auth
import google.auth.transport.requests
import google.oauth2.id_token

app = Flask(__name__)

# --- Configuration ---
TARGET_URL = "https://transcriber-gpu-worker-[PROJECT_HASH].europe-west4.run.app" # Замените на URL вашего Cloud Run
API_KEY = "your-super-secret-api-key" # Замените на ваш ключ

def get_gcp_token():
    try:
        auth_req = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(auth_req, TARGET_URL)
        return token
    except Exception as e:
        print(f"Error getting GCP token: {e}")
        return None

@app.route('/<path:path>', methods=['GET', 'POST'])
def proxy(path):
    client_api_key = request.headers.get('X-API-Key')
    if client_api_key != API_KEY:
        return "Unauthorized", 401

    gcp_token = get_gcp_token()
    if not gcp_token:
        return "Could not authenticate to GCP", 500

    headers = {
        'Authorization': f'Bearer {gcp_token}',
    }
    if 'Content-Type' in request.headers:
        headers['Content-Type'] = request.headers['Content-Type']
    
    try:
        resp = requests.request(
            method=request.method,
            url=f"{TARGET_URL}/{path}",
            headers=headers,
            data=request.get_data(),
            stream=True
        )
        return Response(resp.iter_content(chunk_size=1024), status=resp.status_code, content_type=resp.headers.get('Content-Type'))
    except Exception as e:
        return f"Error during request forwarding: {e}", 502

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
```

**Скрипт запуска (`startup-script.sh`):**
```bash
#!/bin/bash
apt-get update
apt-get install -y python3-pip python3-venv
mkdir -p /opt/proxy
cd /opt/proxy
python3 -m venv venv
source venv/bin/activate
pip install Flask requests google-auth
# Вставьте сюда содержимое proxy_server.py с помощью cat <<'EOF' > proxy_server.py ... EOF
nohup venv/bin/python proxy_server.py &
```
*Чтобы использовать этот скрипт, нужно передать его при создании VM через флаг `--metadata-from-file startup-script=startup-script.sh`.*

---

## Шаг 6: Настройка клиента

В `gcp_client.py` нужно указать публичный IP-адрес вашей VM и API-ключ.

```python
# --- Configuration ---
WORKER_URL = "http://[YOUR_VM_EXTERNAL_IP]"
API_KEY = "your-super-secret-api-key" # Должен совпадать с ключом на прокси-сервере
```
Функция аутентификации также упрощается:
```python
def get_authed_session():
    """Creates a session with the proxy API key."""
    session = requests.Session()
    session.headers.update({"X-API-Key": API_KEY})
    return session
```
После этого клиент готов к работе.
