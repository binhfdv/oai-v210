# A repo to store OAI 5G v2.1.0 and UERANSIM v3.2.6

## This README contains instructions to run OAI-5G Core, OAI-O-RAN and UERANSIM

## Deploy OAI-5G Core
```
cd ~/oai-v210/charts/oai-5g-core/oai-5g-basic
helm dependency update

helm install oai-5g-basic . -n oai
```

## Deploy OAI-O-RAN
```
cd ~/oai-v210/charts/oai-5g-ran/oai-cu-cp
helm install oai-cu-cp .

helm install oai-cu-up ../oai-cu-up 
helm install oai-du ../oai-du
helm install oai-nr-ue ../oai-nr-ue

export UEPOD=$(kubectl get pods -l app.kubernetes.io/name=oai-nr-ue -o jsonpath="{.items[*].metadata.name}" -n oai)
kubectl exec -it $UEPOD -- bash

#ping towards spgwu/upf
ping -I oaitun_ue1 12.1.1.1

#ping towards google dns
ping -I oaitun_ue1 8.8.8.8
```

# ----------------------------------
# To use UERANSIM instead

## Build UERANSIM
```
cd UERANSIM/

sudo apt update && sudo apt upgrade -y

sudo apt install make gcc g++ libsctp-dev lksctp-tools iproute2 -y
sudo snap install cmake --classic
```

## Run RAN
```
sudo apt install net-tools -y
python3 config_UERAN.py
./build/nr-gnb -c ./build/OAI-gnb.yaml

sudo ./build/nr-ue -c ./build/OAI-ue.yaml -i imsi-001010000000101
sudo ./build/nr-ue -c ./build/OAI-ue.yaml -i imsi-001010000000102

ping -c 3 -I uesimtun0 google.com
ping -c 3 -I uesimtun1 google.com
```
# ----------------------------------

## Uninstall all deployments
```
Ctrl + C in terminals running UERANSIM to stop processes
helm uninstall $(helm list -aq -n oai) -n oai
```


## Roadmap
### 1. AF implementation
* AF influence traffic for dynamic traffic steering
### 2. OAI-RIC integration
* rApp & xApp for Traffic steering use case