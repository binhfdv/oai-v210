apt update
apt install -y nftables
nft add table input_table
nft 'add chain input_table input {type filter hook input priority -300;}'
nft 'add rule input_table input ip protocol udp udp checksum set 0'