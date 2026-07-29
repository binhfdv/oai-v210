# Anomaly Detection Deployment Guide

## Image Tag

Use image tag: **`detect`**

## Values to Update

Set the `detect` image tag in the `values.yaml` of the following charts:

- `nearRT-ric`
- `xapp-kpm-moni`
- `xapp-rc-prb-rrc-release`
- `oai-cu-cp-slice`
- `oai-cu-up-slice`
- `oai-du-slice`

All other charts use their default values.

## hostInterface: "enp1s0f0"
Change "enp1s0f0" with interface in your host machine.

---

## Prerequisites

### Kubernetes Cluster

Follow the [K8s installation guide](https://github.com/binhfdv/k8s-prometheus-grafana). In short, complete steps **1.2, 6, 7, 8**:

- **1.2** — configure Docker as the container runtime
- **6** — taint the node
- **7** — label the node as `node-role=core` (all deployments target this role by default)
- **8** — install Multus CNI, create the `oai` namespace

### Helm

Version **v3.19.0** is required.

---

## Deploy

```bash
cd oai-v210/
NUM_UES_SLICE1=1 NUM_UES_SLICE2=1 ./deploy_anomaly.sh /home/lapdk/workspace/oai-v210 all
# Replace /home/lapdk/workspace/oai-v210 with your actual workspace path
```

### Expected Pod State

```
kubectl get pods -o wide
```

```
NAME                                       READY   STATUS    RESTARTS   AGE     IP            NODE    NOMINATED NODE   READINESS GATES
cleaner-kpm-moni-6674c46465-znlxk          1/1     Running   0          40s     10.244.0.84   lapdk   <none>           <none>
oai-5g-slicing-mysql-6bbf946445-n744b      1/1     Running   0          3m18s   10.244.0.64   lapdk   <none>           <none>
oai-amf-7fbd477fbc-7wp8w                   1/1     Running   0          3m18s   10.244.0.65   lapdk   <none>           <none>
oai-ausf-5f746ff774-9w5wx                  1/1     Running   0          3m18s   10.244.0.66   lapdk   <none>           <none>
oai-cu-cp-69f9769469-8rwt9                 1/1     Running   0          2m5s    10.244.0.76   lapdk   <none>           <none>
oai-cu-up-65dc664fd8-xkmgl                 1/1     Running   0          2m      10.244.0.77   lapdk   <none>           <none>
oai-du-958bb496b-jxld4                     1/1     Running   0          110s    10.244.0.78   lapdk   <none>           <none>
oai-lmf-fc4699b9c-86vtc                    1/1     Running   0          3m18s   10.244.0.62   lapdk   <none>           <none>
oai-nearrt-ric-74c7dc4d57-jwnxl            1/1     Running   0          2m11s   10.244.0.75   lapdk   <none>           <none>
oai-nr-ue-1-66f5c7d64f-r89xt               2/2     Running   0          99s     10.244.0.79   lapdk   <none>           <none>
oai-nr-ue-2-fccfdd58f-s74n4                2/2     Running   0          89s     10.244.0.80   lapdk   <none>           <none>
oai-nrf-ccbb5db6d-4fc9r                    1/1     Running   0          3m18s   10.244.0.67   lapdk   <none>           <none>
oai-smf-slice1-8dc995c4d-xgw2r             1/1     Running   0          2m53s   10.244.0.71   lapdk   <none>           <none>
oai-smf-slice2-f77f45f45-464wg             1/1     Running   0          2m47s   10.244.0.72   lapdk   <none>           <none>
oai-traffic-server-69b85d4f57-5k8q7        2/2     Running   0          3m18s   10.244.0.63   lapdk   <none>           <none>
oai-udm-78b57b6bf-gf6gp                    1/1     Running   0          3m18s   10.244.0.69   lapdk   <none>           <none>
oai-udr-7d4749cc6b-nbnxq                   1/1     Running   0          3m18s   10.244.0.61   lapdk   <none>           <none>
oai-upf-slice1-66f85cd844-mcblj            2/2     Running   0          2m37s   10.244.0.73   lapdk   <none>           <none>
oai-upf-slice2-7b56c87775-5v97j            2/2     Running   0          2m16s   10.244.0.74   lapdk   <none>           <none>
watcher-kpm-moni-764ddfd959-vm2dj          1/1     Running   0          41s     10.244.0.85   lapdk   <none>           <none>
xapp-kpm-moni-78bf9584fc-vcdfn             1/1     Running   0          56s     10.244.0.81   lapdk   <none>           <none>
xapp-rc-prb-rrc-release-6db6b79b5f-4lh9n   1/1     Running   0          49s     10.244.0.82   lapdk   <none>           <none>
```

---

## Start ATD Servers

Start one server per UPF slice from the `oai-anomaly-detection` directory.

**UPF Slice 1**
```bash
cd oai-anomaly-detection/
bash atd-server1.sh
```

**UPF Slice 2**
```bash
cd oai-anomaly-detection/
bash atd-server2.sh
```

---

## Generate Traffic

### Using ATD Paper Traffic Generator -> this one need to debug if it works.

**UE 1**
```bash
kubectl exec -it deployment/oai-nr-ue-1 -c debug -- bash
pip3 install pandas
cd traffic-gen/generate-ue-traffic
python3 generate-ue1.py
```

**UE 2**
```bash
kubectl exec -it deployment/oai-nr-ue-2 -c debug -- bash
pip3 install pandas
cd traffic-gen/generate-ue-traffic
python3 generate-ue2.py
```

### Quick Ping Test (UE 1)

```bash
kubectl exec -it deployment/oai-nr-ue-1 -c debug -- bash
ping -I oaitun_ue1 10.1.2.14 -f
```

---

## Observing Results

- **KPM metrics** — watch for changes at `oai-v210/helm-flexric/watcher-kpm-moni/data/clean/`
- **RC xApp logs** — `kubectl logs deployment/xapp-rc-prb-rrc-release`
