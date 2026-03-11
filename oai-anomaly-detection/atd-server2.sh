#!/bin/bash

UPF=$(kubectl get pods -n oai -l app.kubernetes.io/name=oai-upf-slice2 -o jsonpath="{.items[0].metadata.name}")
kubectl exec -n oai "$UPF" -c pktserver -- python3 /oai-anomaly-detection/anomaly-detection-server-slice2.py
