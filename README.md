# A testbed for O-RAN Research and Implementation

## This README contains instructions to run OAI-5G Core, OAI-O-RAN, UERANSIM, OAI-FlexRIC

## Deploy OAI-5G Core
```
# Should use kubens to change namespace
kubens oai

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
ping -c 3 -I oaitun_ue1 12.1.1.1

#ping towards google dns
ping -c 3 -I oaitun_ue1 8.8.8.8
```

## Or use scripts to deploy OAI
```
kubens oai
cd ~/oai-v210

# before running the below command, this scenario does not include RIC,
# so change images from CUCP/CUUP/DU values.yaml to not use ddocker122/oai-e2gnb-mono:dev
chmod +x deploy_oai.sh
bash deploy_oai.sh . core cu ue
```

# ----------------------------------
# To use UERANSIM instead
## Cloud
```
helm repo add towards5gs 'https://raw.githubusercontent.com/Orange-OpenSource/towards5gs-helm/main/repo/'
helm repo update
helm search repo

cd ~/oai-v210/towards5gs-helm/charts/ueransim
helm dependency update
helm install ueransim .
```

## Baremetal
### Build UERANSIM
```
cd UERANSIM/

sudo apt update && sudo apt upgrade -y

sudo apt install make gcc g++ libsctp-dev lksctp-tools iproute2 -y
sudo snap install cmake --classic
```

### Run RAN
```
sudo apt install net-tools -y
python3 config_UERAN.py
./build/nr-gnb -c ./build/OAI-gnb.yaml

sudo ./build/nr-ue -c ./build/OAI-ue.yaml -i imsi-001010000000101
sudo ./build/nr-ue -c ./build/OAI-ue.yaml -i imsi-001010000000102

ping -c 3 -I uesimtun0 google.com
ping -c 3 -I uesimtun1 google.com

curl -I --interface uesimtun0 google.com
```
# ----------------------------------

## Uninstall all deployments
```
Ctrl + C in terminals running UERANSIM to stop processes
helm uninstall $(helm list -aq -n oai) -n oai
```

## Debugging
```
# sample to run tcpdump, curl, etc. in upf (same for others) pod when tcpdump, curl, etc. is not available in the pod
# --target is name of container in pod

export PODNAME=$(kubectl get pods -l app.kubernetes.io/name=oai-upf -o jsonpath="{.items[*].metadata.name}" -n oai)
kubectl debug -it $PODNAME --image=nicolaka/netshoot --target=upf -- bash

# check helm charts render
helm template ueransim ./dir/to/charts -f values.yaml > rendered.yaml

# check multus network attachments
kubectl get network-attachment-definition
```

# Roadmap
# 1. AF implementation
* AF influence traffic for dynamic traffic steering
# 2. OAI-RIC integration
* rApp & xApp for Traffic steering use case

## FlexRIC
### Using Helm
```
cd helm-flexric/
bash deploy_flexric.sh
```
### Baremetal (read more on https://gitlab.eurecom.fr/mosaic5g/flexric/-/tree/dev?ref_type=heads)
```
sudo apt update -y
sudo apt upgrade -y
sudo apt install -y build-essential
sudo apt install -y gcc-13 g++-13 cpp-13
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-13 100 --slave /usr/bin/g++ g++ /usr/bin/g++-13 --slave /usr/bin/gcov gcov /usr/bin/gcov-13
sudo update-alternatives --config gcc # chose gcc-13

sudo apt install libsctp-dev cmake-curses-gui libpcre2-dev

sudo apt install -y automake bison

git clone --branch release-4.1 --single-branch https://github.com/swig/swig.git
cd swig
./autogen.sh
./configure --prefix=/usr/
make -j8
sudo make install

# ...follow instructions on mosaic5g/Flexric repo

```

## Flexric + OAI O-RAN
```
chmod +x deploy_oai.sh
# the below command is to run 5g Core, nearRT-RIC, gNB, NR-UE, xApp kpm
bash deploy_oai.sh . core ric gnb ue-gnb kpm

# the below command is to run 5g Core, nearRT-RIC, CU/DU, NR-UE, xApp kpm
# make sure to use image ddocker122/oai-e2gnb-mono:dev for CUCP/CUUP/DU
bash deploy_oai.sh . core ric cu ue-gnb kpm

# use docker compose, by default, it runs 5g Core, nearRT-RIC, CU/DU, NR-UE, xApp kpm, xApp gtp-mac-rlc-pdcp, xApp rc
cd docker-compose
sudo docker compose -f docker-compose-oai-v210.yaml up -d
sudo docker compose -f docker-compose-oai-v210.yaml down
```