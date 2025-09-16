# Deploy on multi-server

## Set up routes on all servers

```bash
sudo sysctl -w net.ipv4.conf.all.rp_filter=0
sudo sysctl -w net.ipv4.conf.default.rp_filter=0
sudo sysctl -w net.ipv4.conf.enp0s31f6.rp_filter=0
sudo sysctl -w net.ipv4.conf.demo-oai.rp_filter=0

sudo sysctl -w net.ipv4.ip_forward=1

sudo modprobe br_netfilter
sudo sysctl -w net.bridge.bridge-nf-call-iptables=1

sudo iptables -L FORWARD -v -n | head

# if default policy is DROP, allow traffic between host NIC and docker bridge:
sudo iptables -I FORWARD -i enp0s31f6 -o demo-oai -j ACCEPT
sudo iptables -I FORWARD -i demo-oai -o enp0s31f6 -j ACCEPT
# enp0s31f6 is your server interface
```

## Set up routes
1. 5G CORE
2. gNB
    ```bash
        sudo ip route add 192.168.70.128/26 via 192.168.0.242 dev enp0s31f6
        # check the route
        ip route get 192.168.70.132
        
        # should have output: 192.168.70.132 via 192.168.0.233 dev enp0s31f6 src 192.168.0.239 uid 1000

        # ip of CORE host: 192.168.0.233
        # interface of gNB host: enp0s31f6

    ```
3. UE
    ```bash
        sudo ip route add 192.168.71.128/26 via 192.168.0.239 dev enp0s31f6
        # check the route
        ip route get 192.168.71.141
        # should have output: 192.168.71.141 via 192.168.0.239 dev enp0s31f6 src 192.168.0.141 uid 1000

        # ip of gNB host: 192.168.0.239
        # interface of UE host: enp0s31f6
    ```

Note: to debug the connection between servers, have to care about where exactly the packets suck, e.g, Do they come out the host? Do they reach the guest host?. Use `tcpdump` to debug.

## Configuration for RAN are available in ran-conf folder, make changes and run python programs to generate configs.

## Deployments on servers
### 5G CORE
```bash
docker compose -f docker-compose-oai-v210.yaml up -d mysql oai-udr oai-udm oai-ausf oai-nrf oai-amf oai-smf oai-upf oai-ext-dn

docker compose -f docker-compose-oai-v210.yaml down
```

### gNB
```bash
# gNB
docker compose -f docker-compose-oai-v210-ran-ric.yaml up -d oai-cucp oai-cuup oai-du

# RIC, only run this after the UE connected to gNB
docker compose -f docker-compose-oai-v210-ran-ric.yaml up -d oai-nearrt-ric

# wait for oai-nearrt-ric to connect to all RAN function and UE can ping oai-ext-dn first, 
docker compose -f docker-compose-oai-v210-ran-ric.yaml up -d oai-xapp-kpm oai-xapp-gtp-mac oai-xapp-rc

docker compose -f docker-compose-oai-v210-ran-ric.yaml down
```

### UE
```bash
docker compose -f docker-compose-oai-v210-ue.yaml up -d

docker compose -f docker-compose-oai-v210-ue.yaml
```