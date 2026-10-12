# Independent machine gateway simulator

This server is supporting infrastructure, not a mode in the manufacturing platform. It accepts the normal gateway HTTP protocol and calls the platform's authenticated machine-event endpoint. The local launcher starts it on 9002; Compose uses the `gateway` service. Any configured machine ID can be exercised through this boundary.

Standalone startup from `smart-operator/`:

```bash
PLATFORM_ENV_FILE=backend/.env \
PLATFORM_CALLBACK_URL=http://127.0.0.1:8083/api/machine/events \
PORT=9002 python3 infra/machine-simulator/server.py
```

`MACHINE_EVENT_TOKEN` is loaded from the specified ignored environment file or an explicit process environment. The platform and simulator must share it. `SIMULATOR_OPERATION_SECONDS` controls the duration (default 4 seconds). Health and capabilities are exposed at `/health` and `/v1/capabilities`.

POST `/api/v1/machines/{machine_id}/commands` requires the shared Bearer token and accepts `{action:"start",task_id,order_id,dispatch_id,external_id,callback_url}` with HTTP 202 acknowledgement. Duplicate dispatch IDs with identical content return the original acknowledgement and do not repeat the cycle; changed content returns 409. Command history can be queried at `/v1/commands/{dispatch_id}`.

`action:"stop"` addresses the original dispatch ID, task and order. Acknowledged stops return `status:"stopped"`, are idempotent, and suppress any later completion callback from that cycle. The platform requests this through the same boundary before releasing running equipment during reassignment. If an operation has already finished, a stop returns a conflict so the completion callback can be reconciled.

Each cycle sends `started`, then `completed` (or `failed` for configured faults). The callbacks include the dispatch attempt, machine/task IDs and stable `<dispatch_id>:<event>` ID and use the shared Bearer token. Temporary callback failures retry with the same event ID; a superseded task/attempt is not resurrected. Callback URLs must match the configured platform callback, preventing arbitrary command callers from forwarding the integration secret elsewhere.

For infrastructure testing only, POST `/_simulator/faults` with the shared Bearer token and `{machine_id,mode:"failed"}` causes subsequent completion callbacks for that machine to fail. Use `mode:"healthy"` to clear it. With `MACHINE_EVENT_TOKEN` already loaded into your local shell environment:

```bash
curl --fail-with-body http://localhost:9002/_simulator/faults \
  -H "Authorization: Bearer ${MACHINE_EVENT_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"machine_id":"cnc-1","mode":"failed"}'
```

These controls are not linked from the product or exposed to operators. Administrative machine availability is an ordinary platform operation and remains separate from simulated physical faults.

The simulator does not emulate PLC safety interlocks, inventory, dimensional checks or actual machining dynamics. Commands and faults are kept in memory, so restart resets its history. A real gateway needs durable command reconciliation and observed equipment-specific protocol/safety integration. Reference protocol and callback details are in [architecture](../../docs/architecture.md#gateway-protocol).
