echo "Fixing python to capture the traffic"
# These commands is needed in all containers to enable python to capture the udp traffic
docker cp ./fix-bug.sh rfsim5g-hcs-encoder:/
docker exec rfsim5g-hcs-encoder  bash /fix-bug.sh

docker cp ./fix-bug.sh rfsim5g-oai-nr-ue:/
docker cp ./iptables_ue.sh rfsim5g-oai-nr-ue:/
docker exec rfsim5g-oai-nr-ue bash /fix-bug.sh
docker exec rfsim5g-oai-nr-ue bash /iptables_ue.sh # set the iptables random packet loss 15%

docker cp ./fix-bug.sh rfsim5g-hcs-decoder:/
docker cp ./iptables_decoder.sh rfsim5g-hcs-decoder:/
docker exec rfsim5g-hcs-decoder bash /fix-bug.sh
docker exec rfsim5g-hcs-decoder bash /iptables_decoder.sh # set the iptables random packet loss 20%

# docker cp ./fix-bug.sh rfsim5g-hcs-recoder:/ #recoder
# docker exec rfsim5g-hcs-recoder bash /fix-bug.sh

# install tcpreplay 
echo "Install tcpreplay on ext-dn"
docker cp ./host3/tcpreplay-4.4.2 rfsim5g-oai-ext-dn:/
docker exec rfsim5g-oai-ext-dn chmod +x /tcpreplay-4.4.2/configure 
docker exec rfsim5g-oai-ext-dn bash /tcpreplay-4.4.2/install.sh
