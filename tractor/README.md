# This folder contains open-source to deploy TRACTOR xApp in microservice style.

## 1. Simulate KPM to run on local
### Use Docke compose:
```bash
docker compose up -d
docker xapp-orchestrator

docker compose down
```

### Use K8s deployment with helm chart, you already have the K8s cluster
```bash
cd ./helm-tractor/tractor-basic
helm dependency update

helm install tractor-basic .
kubectl logs -l app=tractor-orchestrator

helm uninstall tractor-basic
```
## 2. Run on Colosseum
