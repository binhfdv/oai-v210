apt update
apt-get install -y iptables
iptables -A INPUT -s 192.168.72.145 -d 12.1.1.2 -m statistic --mode random --probability 0.15 -j DROP