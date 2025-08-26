# This folder is to develop xApp RAN Control

## For source codes, find them here https://openaicellular.github.io/oaic/OAIC-2024-Workshop-oai-flexric-documentation.html

## In this folder, source codes are already cloned.


## RAN & UE - at commit `oaic_workshop_2024_v1` with E2 interface
```bash
cd oai-oaic_workshop_2024_v1/cmake_targets/
./build_oai -I -w SIMU --gNB --nrUE --build-e2 --ninja
```

## FlexRIC - at commit `beabdd072`
```bash
cd flexric-beabdd072/
mkdir build
cd build
cmake ../
make -j`nproc`
sudo make install
```

## Let's run it
### Terminal 1 - Core Network
```bash
cd ./oai-cn5g
docker compose up -d
docker ps 
```

All NFs should be healthy.

Now, we start gNB on Terminal 1

```bash
cd ../oai-oaic_workshop_2024_v1/cmake_targets/ran_build/build/
sudo ./nr-softmodem -O ../../../targets/PROJECTS/GENERIC-NR-5GC/CONF/gnb.sa.band78.fr1.106PRB.usrpb210.conf --gNBs.[0].min_rxtxtime 6 --rfsim --sa
```

### Terminal 2 - UE
```bash
cd ./oai-oaic_workshop_2024_v1/cmake_targets/ran_build/build/
sudo ./nr-uesoftmodem -r 106 --numerology 1 --band 78 -C 3619200000 --rfsim --sa --uicc0.imsi 001010000000001 --rfsimulator.serveraddr 127.0.0.1
```

### Terminal 3 - FlexRIC nearRT-RIC
```bash
./flexric-beabdd072/build/examples/ric/nearRT-RIC
```

### Terminal 4 - UP & DL test
```bash
# Uplink
ping 192.168.70.135 -I oaitun_ue1 -c 3

# Downlink
UE_IP=$(ip -4 addr show oaitun_ue1 | grep -oP '(?<=inet\s)\d+(\.\d+){3}')
docker exec -it oai-ext-dn ping $UE_IP -c 3

# Streaming Traffic with iPerf - Uplink
docker exec -it oai-ext-dn iperf -s -i 1 -fk -B 192.168.70.135

# Streaming Traffic with iPerf - Downlink
iperf -s -u -i 1 -B $UE_IP

```

Run the command for UL, DL in Terminal 5 accordingly

### Terminal 5 - UP & DL test
```bash
UE_IP=$(ip -4 addr show oaitun_ue1 | grep -oP '(?<=inet\s)\d+(\.\d+){3}')

# Streaming Traffic with iPerf - Uplink
iperf -c 192.168.70.135 -i 1 -b 10M -B $UE_IP

# To test with xApp-RC - Uplink
iperf -c 192.168.70.135 -i 1 -b 10000M -B $(ip -4 addr show oaitun_ue1 | grep -oP '(?<=inet\s)\d+(\.\d+){3}') -t 200

# Streaming Traffic with iPerf - Downlink
docker exec -it oai-ext-dn iperf -u -t 100 -i 1 -fk -B 192.168.70.135 -b 10M -c $UE_IP
```

UL & DL work well so now clean Terminal 4 & 5 to deploy xApps

### Terminal 4 - KPIMON xApp
```bash
cd ./flexric-beabdd072
./build/examples/xApp/c/monitor/xapp_kpm_moni
```

Should get result like:
```
     10 KPM ind_msg latency = 1754640902858966 [μs]
[xApp]: E42 SUBSCRIPTION DELETE RESPONSE rx
UE ID type = gNB, amf_ue_ngap_id = 1
ran_ue_id = 1
DRB.PdcpSduVolumeDL = 0 [kb]
DRB.PdcpSduVolumeUL = 0 [kb]
DRB.RlcSduDelayDl = 0.00 [μs]
DRB.UEThpDl = 0.00 [kbps]
DRB.UEThpUl = 0.00 [kbps]
RRU.PrbTotDl = 10 [PRBs]
RRU.PrbTotUl = 105 [PRBs]
[xApp]: Sucessfully stopped 
Test xApp run SUCCESSFULLY
```

### Terminal 5 - RAN Control (RC) xApp
```bash
cd ./flexric-beabdd072
./build/examples/xApp/c/kpm_rc/xapp_kpm_rc
```

Should get result like:

```
     49 KPM ind_msg latency = 1754641010141212 [μs]
UE ID type = gNB, amf_ue_ngap_id = 1
ran_ue_id = 1
DRB.PdcpSduVolumeDL = 0 [kb]
DRB.PdcpSduVolumeUL = 0 [kb]
DRB.RlcSduDelayDl = 0.00 [μs]
DRB.UEThpDl = 0.00 [kbps]
DRB.UEThpUl = 0.00 [kbps]
RRU.PrbTotDl = 0 [PRBs]
RRU.PrbTotUl = 10 [PRBs]
[xApp]: CONTROL-REQUEST tx 

     50 KPM ind_msg latency = 1754641010241762 [μs]
UE ID type = gNB, amf_ue_ngap_id = 1
ran_ue_id = 1
DRB.PdcpSduVolumeDL = 0 [kb]
DRB.PdcpSduVolumeUL = 0 [kb]
DRB.RlcSduDelayDl = 0.00 [μs]
DRB.UEThpDl = 0.00 [kbps]
DRB.UEThpUl = 0.00 [kbps]
RRU.PrbTotDl = 0 [PRBs]
RRU.PrbTotUl = 15 [PRBs]
[xApp]: CONTROL ACK rx
[xApp]: Successfully received CONTROL-ACK 
```

In the gNB side, we see this:
```
QoS flow mapping configuration
DRB ID 5 
List of QoS Flows to be modified in DRB
qfi = 10, dir 1 
[E2-AGENT]: CONTROL ACKNOWLEDGE tx
[NR_MAC]   Frame.Slot 0.0
UE RNTI 36df CU-UE-ID 1 in-sync PH 52 dB PCMAX 20 dBm, average RSRP -44 (16 meas)
UE 36df: UL-RI 1, TPMI 0
UE 36df: dlsch_rounds 84500/0/0/0, dlsch_errors 0, pucch0_DTX 0, BLER 0.00000 MCS (0) 9
UE 36df: ulsch_rounds 39190/25/5/2, ulsch_errors 1, ulsch_DTX 0, BLER 0.00000 MCS (0) 9 (Qm 2  dB) NPRB 5  SNR 51.0 dB
UE 36df: MAC:    TX      141862640 RX       18553458 bytes
UE 36df: LCID 1: TX            531 RX            290 bytes
UE 36df: LCID 2: TX              0 RX              0 bytes
UE 36df: LCID 4: TX      134306108 RX       13801034 bytes
```

For tutorials, check video: https://www.youtube.com/watch?v=IIcLjdneCy0&list=PLm7Cwn08hhZXqs-3ReU-R9gYByYayDzjD&ab_channel=OAIC