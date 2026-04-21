# SDN-Based Simple QoS Priority Controller Using Mininet and OpenFlow

## Problem Statement

In traditional networks, all traffic competes equally for bandwidth. When a bulk transfer floods the network, real-time traffic like video streams suffers the same delays — there is no way to differentiate or prioritize traffic without reprogramming every switch individually.

This project implements an **SDN-based Simple QoS Priority Controller** using Mininet and Open vSwitch (OVS). The controller identifies traffic types by source IP, assigns each type to a priority queue, installs OpenFlow match-action flow rules, and demonstrates measurable latency improvement for high-priority traffic under congestion.

---

## Network Topology

```
h1 (HIGH   - 10.0.0.1) ─┐
h2 (LOW    - 10.0.0.2) ──┤── s1 ══(50 Mbps bottleneck)══ s2 ──── h4 (server  - 10.0.0.4)
h3 (MEDIUM - 10.0.0.3) ──┘                                   └─── h5 (monitor - 10.0.0.5)
```

- **s1** — access switch, QoS rules and HTB queues installed here
- **s2** — distribution switch, connects to server and monitor
- **50 Mbps bottleneck** — the constrained link where congestion occurs and QoS takes effect

---

## QoS Policy

| Host | IP | Traffic Type | Queue | Min Bandwidth | Max Bandwidth | OF Priority |
|------|----|-------------|-------|--------------|--------------|-------------|
| h1 | 10.0.0.1 | High (video/real-time) | Queue 0 | 20 Mbps | 50 Mbps | 300 |
| h3 | 10.0.0.3 | Medium (normal) | Queue 1 | 10 Mbps | 30 Mbps | 200 |
| h2 | 10.0.0.2 | Low (bulk/background) | Queue 2 | 5 Mbps | 15 Mbps | 100 |

---

## SDN Logic and Flow Rule Design

The controller logic is implemented in `qos_project.py` using direct OpenFlow commands via `ovs-ofctl`. The following flow rules are installed on s1:

```
priority=1000  arp                        actions=normal
priority=900   icmp                       actions=normal
priority=300   ip, nw_src=10.0.0.1       actions=mod_nw_tos:40, normal
priority=200   ip, nw_src=10.0.0.3       actions=mod_nw_tos:20, normal
priority=100   ip, nw_src=10.0.0.2       actions=mod_nw_tos:10, normal
priority=1                                actions=normal
```

- **Match field**: source IP address identifies the traffic type
- **Action**: DSCP mark applied to packet, then forwarded normally
- **HTB queues**: enforce bandwidth guarantees at the port level
- **ARP and ICMP** get highest priorities to ensure connectivity always works

---

## Setup and Installation

### Requirements
- Ubuntu 20.04 / 22.04
- Python 3.x
- Mininet
- Open vSwitch

### Install dependencies
```bash
bash setup.sh
```

This installs: mininet, openvswitch-switch, openvswitch-testcontroller, iperf, xterm, tcpdump, net-tools.

### Install missing controller binary
```bash
sudo apt install openvswitch-testcontroller -y
sudo ln -sf /usr/bin/ovs-testcontroller /usr/bin/controller
```

---

## How to Run

### Step 1 — Clean up any leftover state
```bash
sudo mn -c
```

### Step 2 — Start the project
```bash
sudo python3 qos_project.py
```

### Step 3 — You will see
```
*** [QoS Setup] Creating HTB queues on s1-eth4
    Queue 0 (HIGH)   : min=20Mbps  max=50Mbps
    Queue 1 (MEDIUM) : min=10Mbps  max=30Mbps
    Queue 2 (LOW)    : min= 5Mbps  max=15Mbps
*** [Controller] Installing OpenFlow flow rules on s1
    [HIGH  ] 10.0.0.1 → queue 0  (OF priority 300)
    [MEDIUM] 10.0.0.3 → queue 1  (OF priority 200)
    [LOW   ] 10.0.0.2 → queue 2  (OF priority 100)
mininet>
```

---

## Test Scenarios

### Scenario 1 — Baseline Connectivity

```bash
mininet> pingall
mininet> h1 ping -c 10 10.0.0.4
mininet> h2 ping -c 10 10.0.0.4
```

**Expected result**: 0% packet loss, all hosts reachable, latency ~9ms for all hosts with no congestion.

### Scenario 2 — QoS Under Congestion

Open xterm windows:
```bash
mininet> xterm h1 h2 h4
```

In h4 xterm — start iperf server:
```bash
iperf -s &
```

In h2 xterm — flood the bottleneck:
```bash
iperf -c 10.0.0.4 -t 120 -b 45M
```

Back in Mininet CLI — measure latency for both hosts simultaneously:
```bash
mininet> h1 ping -c 20 10.0.0.4
mininet> h2 ping -c 20 10.0.0.4
```

**Expected result**:
```
h1 avg latency:  (HIGH queue — protected)
h2 avg latency:  (LOW queue  — deprioritized)
```

The latency difference proves QoS is working — same physical bottleneck link, different treatment based on priority queue.

---

## Verification Commands

```bash
# Show installed OpenFlow flow rules
mininet> sh ovs-ofctl dump-flows s1

# Show HTB queue configuration
mininet> sh ovs-vsctl list Queue

# Show QoS policy attached to port
mininet> sh ovs-vsctl list QoS

# Show packet and byte counts per port
mininet> sh ovs-ofctl dump-ports s1

# Show topology
mininet> nodes
mininet> links
mininet> net
```

---

## Expected Output — dump-flows s1

```
priority=1000,arp              actions=NORMAL
priority=900,icmp              actions=NORMAL
priority=300,ip,nw_src=10.0.0.1  actions=mod_nw_tos:40,NORMAL
priority=200,ip,nw_src=10.0.0.3  actions=mod_nw_tos:20,NORMAL
priority=100,ip,nw_src=10.0.0.2  actions=mod_nw_tos:10,NORMAL
priority=1                     actions=NORMAL
```

---

## Project Structure

```
sdn-qos-priority-controller/
├── qos_project.py     # Main project — topology + controller logic + QoS setup
├── setup.sh           # Dependency installer for Ubuntu 22.04
├── test_qos.sh        # Test scenario instructions
├── README.md          # This file
└── screenshots/       # Proof of execution
    ├── dump_flows.png
    ├── list_queue.png
    ├── pingall.png
    ├── h1_ping_congestion.png
    ├── h2_ping_congestion.png
    └── dump_ports.png
```

---

## References

1. Mininet — http://mininet.org
2. Open vSwitch — https://www.openvswitch.org
3. OpenFlow 1.0 Specification — https://opennetworking.org
4. Linux HTB Queuing — https://tldp.org/HOWTO/Traffic-Control-HOWTO
5. Mininet Walkthrough — http://mininet.org/walkthrough
