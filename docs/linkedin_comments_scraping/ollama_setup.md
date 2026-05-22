# Ollama Setup (Local LLM)

Ollama lets you run open-source LLMs on your own machine and use them as the
OpenOutreach LLM provider — no API key or external service required.

---

## 1. Install Ollama

### macOS / Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Docker

The official Ollama image (CPU only):

```bash
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
```

For GPU support, see the [Ollama Docker docs](https://hub.docker.com/r/ollama/ollama).

---

## 2. Pull a model

```bash
# Fast, small — good for classification / qualification
ollama pull llama3

# Larger, better reasoning
ollama pull llama3:70b

# Good for instruction following / tool use
ollama pull mistral
```

Verify:

```bash
ollama list
# NAME              ID             SIZE   MODIFIED
# llama3:latest     ...            4.7GB  2 minutes ago
```

---

## 3. Check the API endpoint

Ollama exposes an OpenAI-compatible REST API on port 11434:

```bash
curl http://localhost:11434/v1/models
# {"object":"list","data":[{"id":"llama3:latest",...}]}
```

This is the endpoint you'll point OpenOutreach at.

---

## 4. Configure OpenOutreach to use Ollama

LLM settings are stored in the `SiteConfig` Django singleton, editable via
Django Admin at `http://localhost:8000/admin/`.

| Field | Value |
|:------|:------|
| `LLM_PROVIDER` | `openai_compatible` |
| `LLM_API_KEY` | `ollama` *(any non-empty string — Ollama doesn't check it)* |
| `AI_MODEL` | `llama3` *(or whichever model you pulled)* |
| `LLM_API_BASE` | `http://localhost:11434/v1` |

`LLM_API_BASE` is only consulted when `LLM_PROVIDER` is `openai_compatible`.

### Via Django Admin (GUI)

1. Start the admin server: `make admin`
2. Open `http://localhost:8000/admin/linkedin/siteconfig/`
3. Set the four fields above and click **Save**.

### Via the `.env` file (alternative)

```dotenv
LLM_PROVIDER=openai_compatible
LLM_API_KEY=ollama
AI_MODEL=llama3
LLM_API_BASE=http://localhost:11434/v1
```

Then restart the daemon so it picks up the new values.

---

## 5. Docker networking note

If OpenOutreach is running inside Docker and Ollama is on your host machine,
`http://localhost:11434` will **not** resolve from inside the container.
Use the host's Docker gateway address instead:

```dotenv
LLM_API_BASE=http://host.docker.internal:11434/v1
```

`host.docker.internal` works on macOS and Windows Docker Desktop.
On Linux, use the gateway IP (typically `172.17.0.1`):

```bash
ip route | awk '/default/ { print $3 }'   # prints the gateway IP
```

---

## 6. Using scraped post data with the LLM

The `profile_comment_posts` command outputs a JSON array of post objects.
You can pipe this directly into any script that calls the OpenAI-compatible API:

```bash
# Collect posts
python manage.py profile_comment_posts \
  --profile-url "https://www.linkedin.com/in/some-person/" \
  --limit 10 \
  --dry-run > posts.json

# Feed to a local LLM for summarisation (curl example)
curl http://localhost:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d @- <<EOF
{
  "model": "llama3",
  "messages": [
    {
      "role": "user",
      "content": "Summarise these LinkedIn posts and identify the person's top interests:\n$(cat posts.json)"
    }
  ]
}
EOF
```

Within OpenOutreach itself, the LLM is used for lead **qualification** (via the
ML pipeline in `linkedin/ml/`) and **follow-up generation** (via
`linkedin/agents/follow_up.py`). The post-scraping data can be manually fed to
the same LLM endpoint outside the daemon.

---

## 7. Troubleshooting

| Symptom | Fix |
|:--------|:----|
| `Connection refused` on port 11434 | Ollama is not running — `ollama serve` |
| `model not found` | Pull the model first — `ollama pull <model>` |
| Slow responses | Use a smaller model (`llama3` 8B instead of 70B) |
| Garbled output / very short responses | Increase `num_ctx` via a custom Modelfile |
| `LLM_API_BASE` ignored | Check that `LLM_PROVIDER` is set to `openai_compatible` |
