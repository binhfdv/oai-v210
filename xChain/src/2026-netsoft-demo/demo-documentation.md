# Demo

## Running the demo
Instruction on how to run the demo

We need to create docker volume to be shared between containers
on host3, create the volum by running this command:
```
docker volume create --name shared-data-volume
``` 

### API
.... 

### Front-end
.....

### Containers scripts
#Note: to run the script in background and to keep runing when you close the terminal, use the nohup before the command
#e.g: ` nohup python3 container_cmd.py 192.168.72.160 4000 &`


**ext-dn:**
```
python3 container_cmd.py 192.168.72.160 4000

In Background: 
nohup python3 container_cmd.py 192.168.72.160 4000 &
```

**Gateway:**
```
python3 container_cmd.py 192.168.72.160 4000

In Background: 
nohup python3 container_cmd.py 192.168.72.160 4000 &
```


At the API server container, you should see such logs:
```
Accepted connection from ('192.168.72.135', 34294)
Received from 192.168.72.135: aa7e6f52d0a1
Host is connected: rfsim5g-oai-ext-dn
Accepted connection from ('192.168.72.145', 58924)
Received from 192.168.72.145: d00a8e9f39d7
Host is connected: rfsim5g-hcs-encoder
Accepted connection from ('172.19.0.67', 52734)
Received from 172.19.0.67: 565ce3641a82
Host is connected: rfsim5g-hcs-decoder
```

# Scenarios & Files
    Python files 
        EXt-DN:
            - No python => only tcpreplay
        Gateway
            - gateway.py
       

    Pcap files:
        - vr.pcap
        - haptic.pcap
        - iot.pcap
        - social.pcap



#### Examples:

- At ext-nd: To replay a PCAP file, inside the container run:    
    ```
        tcpreplay -i eth0 vr.pcap    
    ```
## General Notes


## Port Forwarding
To acces the demo UI from the univesity network, you need to use port forwarding on the router (the testbed router) to forward the requests from external network to the internal netwrork
1. login to the router GUI: http://172.31.54.10/
2. Go to the Firewall - Port Forwards page: http://172.31.54.10/cgi-bin/luci/admin/network/firewall/forwards
3. Add new Port forward entry 
