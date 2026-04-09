apt update
apt install -y iptables
iptables -A INPUT -s 172.19.0.66 -d 172.19.0.67 -m statistic --mode random --probability 0.2 -j DROP