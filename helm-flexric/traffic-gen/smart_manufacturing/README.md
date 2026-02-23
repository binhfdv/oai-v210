# Deploy 5G and RAN:
```bash
bash deploy_oai.sh . core ric cu kpm

```

# Deploy 3 or more UEs:
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

# Increase the ID number if having more UEs

# In each UE (check the number UE1, UE2, UE#), start to replay traffic.
cd traffic-gen/smart_manufacturing
./replay_from_ue.sh <ue_folder> oaitun_ue1 [speed]
./replay_from_ue.sh ue_pcaps/ue1 oaitun_ue1 1000
./replay_from_ue.sh ue_pcaps/ue2 oaitun_ue1 1000
./replay_from_ue.sh ue_pcaps/ue3 oaitun_ue1 1000

./replay_from_ue.sh ue_urllc/pcaps/ue1 oaitun_ue1 1000
./replay_from_ue.sh ue_urllc/pcaps/ue2 oaitun_ue1 1000
./replay_from_ue.sh ue_urllc/pcaps/ue3 oaitun_ue1 1000
./replay_from_ue.sh ue_urllc/pcaps/ue4 oaitun_ue1 1000
./replay_from_ue.sh ue_urllc/pcaps/ue5 oaitun_ue1 1000
```

# Capture KPM
- watcher KPM
```bash
cd ../watcher-kpm-moni/
helm install watcher-kpm-moni .
```

- clearer KPM
```bash
cd ../cleaner-kpm-moni/
helm install cleaner-kpm-moni .
```

