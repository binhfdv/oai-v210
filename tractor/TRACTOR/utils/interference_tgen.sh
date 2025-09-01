#!/bin/bash
## HOW TO RUN: ./interference_tgen.sh genesys-gNB genesys-UE genesys-Interferance


if [ ! -d "./interference" ]
  then
    mkdir ./interference
    mkdir ./interference/off
    mkdir ./interference/on
fi

# update the rf scenario number as needed (10042 supports up to 10 UEs)
# see https://colosseumneu.freshdesk.com/support/solutions/articles/61000295793-cellular-scenarios
sshpass -p "scope" ssh $1 "colosseumcli rf start 10042 -c"


sshpass -p "scope" scp radio_tgen.conf $1:/root/radio_api/
sshpass -p "scope" scp radio_tgen.conf $2:/root/radio_api/
sshpass -p "scope" scp ../traffic_gen.py $1:/root/traffic_gen/
sshpass -p "scope" scp ../traffic_gen.py $2:/root/traffic_gen/
    
sshpass -p "scope" ssh $1 "cd /root/radio_api && python3 scope_start.py --config-file radio_tgen.conf" &
sshpass -p "scope" rsync -av ../raw $1:/root/traffic_gen/

sshpass -p "scope" ssh $2 "cd /root/radio_api && python3 scope_start.py --config-file radio_tgen.conf" &
sshpass -p "scope" rsync -av ../raw $2:/root/traffic_gen/

if [ $# -eq 3 ] 
  then
    sshpass -p "sunflower" scp uhd_tx_tone.sh $3:/root/utils/
    mkdir ./interference/on/${3}
fi


sleep 20
clear -x
echo "Configured all SRNs"
sleep 20

for t in ../raw/*.csv
do
  tracename=$(basename ${t})
  echo "TRACE ${tracename}"
  echo "***** Run traffic on gNB *****"
  sshpass -p "scope" ssh -tt $1 "cd /root/traffic_gen && python traffic_gen.py --eNB -f ./raw/${tracename}" &   # this will have to let the next command go through
  gNB_PID=$!
  echo "Sleep for 5 secs"
  sleep 5  # let's wait few seconds
  echo "***** Run traffic on UE *****"
  sshpass -p "scope" ssh -tt $2 "cd /root/traffic_gen && python traffic_gen.py -f ./raw/${tracename}" &
  UE_PID=$!
  sleep 5 # let the traffic start
  
  if [ $# -eq 3 ] 
    then
      sshpass -p "sunflower" ssh $3 "cd /root/utils && sh uhd_tx_tone.sh" &
      sleep 5 # let the tx process start
      int_PID=`sshpass -p "sunflower" ssh $3 "pgrep tx_waveforms"`
      echo "****** Returned PID: ${int_PID} ***********"
  fi
    
  wait $gNB_PID # this will wait until gNB processes terminates
  wait $UE_PID # this will wait until gNB processes terminates
  
  if [ $# -eq 3 ] 
    then
      echo "***** Stopping Interference PID: ${int_PID} *****"
      sshpass -p "sunflower" ssh $3 "kill -INT ${int_PID}"
  fi

  echo "***** Sleeping... *****"
  sleep 5 # sleep for a few second to allow all the classifier outputs to complete producing files
  echo "***** Copy data *****"

  if [ $# -eq 3 ] 
    then
      sshpass -p "scope" scp $1:/root/radio_code/scope_config/metrics/csv/101*_metrics.csv ./interference/on/${3}/${tracename} 
    else
      sshpass -p "scope" scp $1:/root/radio_code/scope_config/metrics/csv/101*_metrics.csv ./interference/off/${tracename}
  fi
  sshpass -p "scope" ssh $1 "rm /root/radio_code/scope_config/metrics/csv/101*_metrics.csv"
  
  echo "***** Completed $t Preparing for next run *****"
  sleep 5 # sleep for a few second to allow the system to settle
  clear -x
  
done


echo "All tests complete"


