# Demo Dashboard




## API Endpoints
Show all hosts with their status:
```
http://192.168.0.2:5000/hosts
```

Show the current running expirement
http://192.168.0.2:5000/current_exp


## Instructions 
In the client containers, save the resuls in folder similar to the traffic types:

vr/cnn_accuracy.csv
vr/cnn_latency.csv
vr/fastinfer_accuracy.csv
vr/fastinfer_latency.csv


```
/demo/data/{current_exp['traffic_type']}

```