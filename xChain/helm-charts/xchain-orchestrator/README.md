# xChain Orchestrator

Lightweight Python/Flask service that manages the xChain chain registry and routing table.
SmartGW polls it periodically to know which xApp chain to forward each traffic class to — no restart required when chains or routing rules change.

## Architecture

```
[xChain Orchestrator :5010]   ← management API
         │
         │ poll every 30s (ORCH_POLL_INTERVAL)
         ▼
[xchain-smartgw :4200]
         │  fast KMeans classify
         ├──────────────────────────────────────┐
         ▼                                      ▼
[tractor-orchestrator :4300]        [xchain-fastinfer :4400]
 normalizer → buffer → model         XGBoost (T=4)
 (CNN/Transformer, T=32)
```

## Default Chains

| Name       | Host                  | Port |
|------------|-----------------------|------|
| tractor    | tractor-orchestrator  | 4300 |
| fastinfer  | xchain-fastinfer      | 4400 |

## Default Routing

| Traffic Class | Chain     |
|---------------|-----------|
| eMBB-mMTC     | tractor   |
| eMBB          | fastinfer |
| mMTC          | fastinfer |
| URLLC-mMTC    | fastinfer |
| URLLC-eMBB    | fastinfer |
| UNKNOWN       | fastinfer |

---

## API Reference

### List chains
```bash
curl http://xchain-orchestrator:5010/chains
```

### Register a new chain
```bash
curl -X POST http://xchain-orchestrator:5010/chains \
  -H "Content-Type: application/json" \
  -d '{"name": "detector", "host": "xchain-detector", "port": 4500}'
```

### Remove a chain
```bash
curl -X DELETE http://xchain-orchestrator:5010/chains/detector
```
> Returns `409` if any routing rule still points to the chain. Update routing first.

### Get routing table
```bash
curl http://xchain-orchestrator:5010/routing
```

### Update routing rules
```bash
curl -X PUT http://xchain-orchestrator:5010/routing \
  -H "Content-Type: application/json" \
  -d '{"URLLC-eMBB": "detector", "URLLC-mMTC": "detector"}'
```
SmartGW picks up the change within `ORCH_POLL_INTERVAL` seconds — no restart needed.

### Health check
```bash
curl http://xchain-orchestrator:5010/health
```
```json
{
  "chains": {
    "tractor":   "ok",
    "fastinfer": "ok"
  }
}
```

---

## Adding a New xApp Chain (example: xchain-detector)

1. Deploy the new xApp into the `oai` namespace.

2. Register it:
```bash
curl -X POST http://xchain-orchestrator:5010/chains \
  -H "Content-Type: application/json" \
  -d '{"name": "detector", "host": "xchain-detector", "port": 4500}'
```

3. Update routing to use it:
```bash
curl -X PUT http://xchain-orchestrator:5010/routing \
  -H "Content-Type: application/json" \
  -d '{"URLLC-eMBB": "detector", "URLLC-mMTC": "detector"}'
```

4. SmartGW automatically connects to the new chain and starts forwarding within `ORCH_POLL_INTERVAL` seconds.

---

## Deployment

Deployed as part of the `xchain-basic` umbrella chart:
```bash
cd helm-charts/xchain-basic
helm dependency update
helm install xchain-basic . -n oai
```

Or standalone:
```bash
helm install xchain-orchestrator helm-charts/xchain-orchestrator -n oai
```

### Port-forward for local access
```bash
kubectl port-forward svc/xchain-orchestrator 5010:5010 -n oai
```

## Configuration

| Env var         | Default               | Description                          |
|-----------------|-----------------------|--------------------------------------|
| TRACTOR_HOST    | tractor-orchestrator  | Pre-loaded tractor chain hostname    |
| TRACTOR_PORT    | 4300                  | Pre-loaded tractor chain port        |
| FASTINFER_HOST  | xchain-fastinfer      | Pre-loaded fastinfer chain hostname  |
| FASTINFER_PORT  | 4400                  | Pre-loaded fastinfer chain port      |
| PORT            | 5010                  | Flask API listen port                |
