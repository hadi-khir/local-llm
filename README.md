# local-llm

A lightweight AI chat app with:

- **Ollama running on your local PC**
- **FastAPI deployed on a VM**
- **A simple HTML/CSS/JS chat UI**
- **Built-in markdown rendering for assistant replies, including fenced code blocks**
- **Session-based login**
- **SSE streaming from backend to browser**

## Architecture

1. The browser talks only to the VM-hosted FastAPI app.
2. The FastAPI app authenticates the user and serves the chat UI.
3. The backend calls Ollama over a private VM-to-PC network path, such as Tailscale.
4. Ollama is never exposed directly to the public internet.

## Local development

```bash
cd /home/hadi/github/local-ai-vm-chat
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## Required environment variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Session signing secret |
| `ADMIN_USERNAME` | Login username |
| `ADMIN_PASSWORD` | Login password |
| `OLLAMA_BASE_URL` | Private URL reachable from the backend, ideally a Tailscale/WireGuard address |
| `OLLAMA_MODEL` | Default Ollama model name |

## VM deployment notes

- Point `OLLAMA_BASE_URL` at the **private** Ollama address reachable from the VM.
- Keep `SESSION_COOKIE_SECURE=true` in production.
- Put the app behind a reverse proxy such as Caddy or Nginx for TLS termination.
- Do not expose Ollama directly through the VM or your home router.

## Docker Compose

```bash
cd /srv/local-ai-vm-chat
mkdir -p data
sudo docker compose up -d --build
```

- The container is named `local-llm`.
- SQLite data is persisted in `./data/app.db`.
- The app is published only on `127.0.0.1:8000`, so nginx can proxy it safely.

For updates:

```bash
cd /srv/local-ai-vm-chat
sudo docker compose up -d --build
```

## Tests

```bash
pytest
```
