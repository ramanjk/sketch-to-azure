# Contributing

Thanks for your interest! This is a Microsoft Hackathon project.

## Principles
- **Zero dependencies.** The app uses only the Python standard library. Please
  don't add `pip`/`requirements.txt` — keep it runnable with a bare `python3`.
- **Demo-safe.** Anything that touches the cloud must degrade gracefully to a
  mock so the demo never breaks on stage.
- **No secrets.** Never commit keys/tokens. Use `az login` or a gitignored
  `.env` (see `whiteboard-to-app/.env.example`).

## Dev loop
```bash
# syntax
python -m py_compile whiteboard-to-app/server.py whiteboard-to-app/azure_iac.py

# run + smoke test (same as CI)
cd whiteboard-to-app && python3 server.py &
curl -s localhost:8012/api/samples
```

## Adding an architecture pattern
- App-style: add to `whiteboard-to-app/sketches.json`; extend `BICEP_FOR` /
  `K8S_KINDS` in `server.py` if new node types are introduced.
- Azure-infra: add a resource block + wiring in `whiteboard-to-app/azure_iac.py`
  and verify it passes `az bicep build`.

## Pull requests
CI (`.github/workflows/smoke-test.yml`) must pass: syntax check + the server
smoke test.
