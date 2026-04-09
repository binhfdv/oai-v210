# nc-demo-paper
This repo hosts the code for the Netsoft 2026.


## Project Structure
### Frontend
The frontend is built using angular, the best way to build or run this project is by using vs-code dev-containers, the project is already configured to run in the dev-container, when you open the folder in vscode, the editor will show a pop-up suggesting to open the project in container.
After opening the project in the dev container, you can run the project using the following commands (inside the container):
```shell
//Run the project:
npm run start

//build the project
npm run build

```
when the gui build finish, the output files (html, css, js) will be stored in the `api/server/templates/browser/` folder, this allow the server to host the GUI and no need to have two containers

## Runt the backend API:
Inside `server` directory, run:

```shell
python3 api_server.py
```


## Build Docker image
Build the docker image, inside the demp-paper folder, run the following command
```
docker build -t demo-api .

```
This command will build both the frontend and backend code into a single docker image





## Running the demo
Instruction on how to run the demo

We need to create docker volume to be shared between containers
on host3, create the volum by running this command:
```
docker volume create --name shared-data-volume
``` 

Then in the Demo container, you need to configure the ENV variables, the `BASE_DIR=/demo/data` is the folder where the data files such as scv files should be stored.  The shared folder should be mapped to the same `BASE_DIR` path. 


### the results files should be stored int he shared folder as follows
```
/demo/data/[traffic_type]/[model]_latency.csv
/demo/data/[traffic_type]/[model]_accuracy.csv

For example:
/demo/data/vr/cnn_accuracy.csv
/demo/data/vr/cnn_latency.csv
/demo/data/vr/fastinfer_accuracy.csv
/demo/data/vr/fastinfer_latency.csv

```


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

