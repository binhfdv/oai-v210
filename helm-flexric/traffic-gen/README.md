# This folder contains dataset and utils to replay traffic from pcap files.

## Traffic dataset:
video has total 11942 packets
audio has total 26425 packets
haptic has total 635000 packets


## Preparation
### Deploy OAI Core, FlexRIC, 1 UE
```bash
$oai-v210$ bash deploy_oai.sh . core ric cu ue-gnb kpm
```

I added a side-container to `ext-dn/traffic-server` to use tcpreplay and other ubuntu libraries. A persistence volume is also added to mount this folder to `ext-dn/traffic-server` pod:

```bash
### charts/oai-5g-core/oai-5g-basic/values.yaml
# Change the hostPath based on the node where the pod will be scheduled. Otherwise, the pod cannot access the traffic-gen folder. You got it :)))

 persistentVolume:
    enabled: true
    name: traffic-gen-pv
    claimName: traffic-gen-pvc
    size: 1Gi
    accessMode: ReadWriteOnce
    hostPath: /home/lapdk/workspace/oai-v210/helm-flexric/traffic-gen # change this one
    reclaimPolicy: Delete
    mountPath: /traffic-gen
```

For example, deployment with 1 UE, for multiple UEs, check folder `oai-nr-ue-gnb`:
```bash
$ kubectl get pods -n oai
NAME                                  READY   STATUS    RESTARTS   AGE
oai-5g-basic-mysql-669d7c4995-hv5q6   1/1     Running   0          93s
oai-amf-75ccfdf695-gk84m              1/1     Running   0          93s
oai-ausf-7d8f9c564b-dhvgp             1/1     Running   0          93s
oai-cu-cp-55c76c86b5-mb6fk            1/1     Running   0          47s
oai-cu-up-85cfc57755-qw4m4            1/1     Running   0          40s
oai-du-85cb98d8b7-d75cs               1/1     Running   0          32s
oai-lmf-5d7cdb7875-k88fj              1/1     Running   0          93s
oai-nearrt-ric-65d5fc9959-wthjj       1/1     Running   0          52s
oai-nr-ue-gnb-7f66d8d4c7-p96z9        1/1     Running   0          25s
oai-nrf-76f8b455d6-ggj5f              1/1     Running   0          93s
oai-smf-856b99bb75-s2vvd              1/1     Running   0          93s
oai-traffic-server-5b777d674d-t2qkg   2/2     Running   0          93s
oai-udm-5649d7b5bc-d4tdl              1/1     Running   0          93s
oai-udr-64849dc4bd-brq99              1/1     Running   0          93s
oai-upf-5f54b5fb48-8tl8x              1/1     Running   0          93s
xapp-kpm-moni-74b48658bf-krn7n        1/1     Running   0          18s
```

Go inside the side container of `traffic-server`:
```bash
export PODNAME=$(kubectl get pods -l app.kubernetes.io/name=oai-traffic-server -o jsonpath="{.items[*].metadata.name}" -n oai) # or just copy the name from screen :))))

kubectl exec -it $PODNAME -c debug -- bash
cd traffic-gen/
chmod +x install_tools.sh
./install_tools.sh
```

## Then, you're ready for the next step...

## How to use?
`All commands below are executed inside traffic-server pod. The ip_change can be run on the host machine because the process may not complete due to resources limit in pod.`
### Change the IPs in pcap:
Manually change the pcap name and IPs in the `ip_change.py`. I don't create this script but you can make a better solution :)).
```bash
input_pcap = "ENCODER_hap.pcap"
output_pcap = "ENCODER_hap_modified.pcap"

# IPs to replace
old_src = "192.168.70.135"   # replace with the original source IP to modify
old_dst = "192.168.70.145"   # replace with the original destination IP to modify
new_src = "10.1.2.14"      # replace with desired new source IP: ext-dnn/traffic-server IP
new_dst = "12.1.1.100"      # replace with desired new destination IP: UE IP
```

Then run the script:
```bash
chmod +x ip_change.py
./ip_change.py
```

### Change the MAC GW of the corresponding UPF and replay:

```bash
chmod +x replay_pcap.sh
./replay_pcap.sh ENCODER_hap_modified.pcap # use the pcap with changed IPs
```

`If you have different OAI setup, you have to check this`

```bash
### replay_pcap.sh
GW="10.1.3.18"        # Gateway IP which is UPF IP
IFACE="net1"          # Interface used for sending which is ext-dn/traffic-server interface
```

#### You might find useful information in `notes` =]].