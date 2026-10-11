# Smart Operator backend

From-scratch FastAPI workflow service for the fan-manufacturing proof of concept. SQLite is the zero-setup default; set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL for deployment.

## Run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8083
```

OpenAPI is available at `http://localhost:8083/docs`. Copy one approved demo reference photograph to each of `data/reference_images/red.jpg`, `green.jpg`, `blue.jpg`, and `white.jpg`. The runtime never depends on `codes/`.

Use `VERIFICATION_PROVIDER=mock` for deterministic demos. It normally approves a submitted image; a filename containing `manual` produces `manual_review`, while one containing `reject` produces `rejected`. `auto` uses OpenAI when `OPENAI_API_KEY` exists and otherwise falls back to mock. `openai` requires the key. Uploaded evidence is limited to 10 MB and persisted under `EVIDENCE_DIR`.

## Main API contract

- `GET /api/catalog`; `POST /api/configurations/validate`; `POST /api/configurations/converse`
- `POST /api/orders`; `GET /api/orders`; `GET /api/orders/{id}`
- `GET /api/operators`; `GET /api/operators/{id}/tasks`; `PUT /api/operators/{id}/availability`
- `GET /api/tasks/{id}`; `POST /api/tasks/{id}/accept|start|complete|handoff`
- `POST /api/tasks/{id}/evidence` (multipart field `file`); `POST /api/tasks/{id}/verify`
- `GET /api/verifications?status=manual_review`; `POST /api/verifications/{id}/review` with `{"decision":"approve|reject","reason":"..."}` (also accepts `outcome: approved|rejected`)
- `GET /api/machines`; `PUT /api/machines/{id}/status`
- `POST /api/machines/tasks/{task_id}/event` with `started|completed|failed` and optional idempotency key `external_id`
- `POST /api/mock/machines/{machine_id}/complete` completes that machine's active task
- `GET /api/supervisor/tasks`; `POST /api/supervisor/tasks/{task_id}/review`
- `GET /api/events?after_id=0`; WebSocket `/ws` (`/ws/events` alias)
- `GET|PUT /api/settings/machine-gateway`; `POST /api/settings/machine-gateway/test`

Order creation accepts `{ "configuration": {"color":"red"} }`; color is the only configurable property. The BOM is fixed structurally and the selected color maps to PR1–PR4 part/bin identifiers. `customer_name` defaults to `Demo Customer` and `confirmed` defaults to `true`. Handoff accepts either `operator_id` or canonical `to_operator_id`.

The gateway setting is persisted and defaults to `http://mock-devices:9002` with `use_mock=true`. Device traffic is server-side. The HTTP adapter expects `GET /health` and `POST /v1/commands` with `commandId`, `machineId`, and `action`; protocol-specific payload adapters can be added behind `MachineGatewayAdapter` without changing workflow code.

## State and adapters

The workflow is `Kitting → CNC machining → Assembly stage 1 → Automated line → Final assembly`. Manual steps requiring verification cannot advance without evidence and an approval. The replaceable boundaries are `AssignmentStrategy`, `MachineAdapter`, `VerificationProvider`, and `MachineGatewayAdapter` in `app/ports.py`.

Run checks with `pytest -q`.
