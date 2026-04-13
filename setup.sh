#!/bin/bash
# setup.sh - installs everything needed on Ubuntu 22.04
# Run: bash setup.sh

set -e
echo "=== Installing dependencies ==="

sudo apt update -y
sudo apt install -y \
    mininet \
    openvswitch-switch \
    openvswitch-testcontroller \
    iperf \
    iperf3 \
    net-tools \
    xterm \
    tcpdump \
    wireshark

echo "=== Starting Open vSwitch ==="
sudo systemctl enable openvswitch-switch
sudo systemctl start openvswitch-switch

echo "=== Verifying ==="
mn --version
ovs-vsctl --version | head -1

echo ""
echo "=== Done! ==="
echo "Run the project with:  sudo python3 qos_project.py"
