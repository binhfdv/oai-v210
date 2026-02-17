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
