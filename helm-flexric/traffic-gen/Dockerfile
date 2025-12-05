FROM ubuntu:22.04
 
RUN apt-get update && \
    apt-get install -y python3-pip && \
    pip3 install scapy
 
COPY install_tools.sh /install_tools.sh
 
RUN chmod +x /install_tools.sh && /install_tools.sh