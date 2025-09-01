# Multiple UEs
To re-play the traffic traces using multiple UEs use the script:
```
sh multi_tgen.sh config_file.txt
```
where config_file.txt is a text file that list the SRN for the experiment on seperate lines. The first line must be the gNB. See ex_config.txt for an example configuration file.
The KPI results will be saved in a new directory called "output_config_file". A text file called "output_config_file.txt" will be generated that lists what trace is used for what UE.

# IPsec
To enable IPsec
```
  start_ipsec.sh genesys-<gNB #node> genesys-<RIC #node>
```
# Adversarial Tools
There are multiple tools to emulate different types of malicious behavior.

## RF Interference
To add RF interference use the script: 
```
sh interference_tgen.sh genesys-<gNB #node> genesys-<UE #node> genesys-<interference #node>
````
Use the `webinar-interactive-v1` SRN for the interfering node.

You can adjust the interference by editing ```uhd_tx_tone.sh```.

## Malicious UE traffic
There are several scripts to generate malicious UE traffic. These scripts were used to generate the data set used in the paper:

- Y. Rumesh, D. Attanayaka, P. Porambage, J.E. Pinola, J.B. Groen, and K. Chowdhury, “Federated Learning for Anomaly Detection in Open RAN: Security Architecture Within a Digital Twin,” 2024 EuCNC & 6G Summit - NET, March 2024.

Please consider citing this paper if you use these scripts.

```interference_tgen_p.sh``` represents a DoS attack by generating uplink packets with poisson distribution timing and gaussian distribution packet size.

```interference_tgen_uf.sh``` replays malicious DoS UDP attacks. The traces in the ./raw folder come from the dataset provided here: https://www.unb.ca/cic/datasets/ddos-2019.html.

```interference_tgen_bh.sh``` represents a bandwidth hog attack and uses the original 5G traces but adds a normally distributed RV to the packet size.
