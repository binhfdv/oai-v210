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
cd ./helm-tractor/
pip3 install ruamel.yaml
# run this in the node where you schedule the pods
# then you have to copy the hostpath changed in
#        modified:   tractor-kpm-simu/values.yaml
#        modified:   tractor-model/values.yaml
#        modified:   tractor-normalizer/values.yaml

# to the files in your control-plane node

./update_hostpath.py embb1010123456002_metrics.csv model.32.cnn.pt cols_maxmin.pkl

cd tractor-basic/
helm dependency update

helm install tractor-basic .
kubectl logs -l app=tractor-orchestrator

helm uninstall tractor-basic
```
## 2. Run on Colosseum
