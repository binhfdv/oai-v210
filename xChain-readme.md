presiquites
K8s cluster
namespace `oai`
configurations
update corresponding hostpaths to xchain-basic/values.yaml
For example, running below command will update hostpath to the sub-charts directly. You can whether update manually to xchain-basic/values.yaml or comment the hostpath lines. Values in xchain-basic/values.yaml will override that of sub-charts.
```
~/xChain/helm-charts$ ./update_hostpath.py model.32.cnn.pt cols_maxmin.pkl
```

6 terminals to show
- service status
- KPM xApp
- traffic replay
- SmartGW
- FastInfer
- TRACTOR

2 terminals in background
- watcher KPM
- clearer KPM

commands on each terminal
- service status
```bash
bash deploy_oai.sh . core ric cu ue-gnb kpm xchain-basic
watch kubectl get pods
```

- KPM xApp
```bash
kubectl logs -l app=oai-xapp-kpm-moni --tail 10 -f
```