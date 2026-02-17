# Deploy 5G and RAN:
```bash
bash deploy_oai.sh . core ric cu kpm

```

# Deploy 3 UEs:
```bash
cd charts/oai-5g-ran/oai-nr-ue-gnb
#python3 deploy_multi_ue.py <num_ues> <node_role>
python3 deploy_multi_ue.py 3 core
```

# Replay traffic
```bash
#UE 1
kubectl exec -it $(kubectl get pods -l app.kubernetes.io/instance=oai-nr-ue-1 -o name | head -n 1) -c debug -- bash

# UE 2
kubectl exec -it $(kubectl get pods -l app.kubernetes.io/instance=oai-nr-ue-2 -o name | head -n 1) -c debug -- bash

# UE 3
kubectl exec -it $(kubectl get pods -l app.kubernetes.io/instance=oai-nr-ue-3 -o name | head -n 1) -c debug -- bash

# In any UE, start to replay traffic.
cd traffic-gen

```