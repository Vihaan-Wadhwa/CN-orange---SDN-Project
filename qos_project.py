#!/usr/bin/env python3
"""
Simple QoS Priority Controller
================================
Ubuntu 22.04 | Mininet + OVS only | No Ryu | No POX | Any Python 3

Architecture:
  h1 (HIGH  10.0.0.1) ─┐
  h2 (LOW   10.0.0.2) ──┤── s1 ══(50Mbps bottleneck)══ s2 ── h4 (server)
  h3 (MED   10.0.0.3) ──┘                                └── h5 (monitor)

Controller logic: Python calls ovs-ofctl/ovs-vsctl directly.
This installs real OpenFlow flow rules and real HTB QoS queues.

Run: sudo python3 qos_project.py
"""

from mininet.net import Mininet
from mininet.node import OVSSwitch, Controller
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import subprocess
import time


# ── QoS Policy ───────────────────────────────────────────────────────────────
# (src_ip, openflow_priority, queue_id, label, min_bps, max_bps)
QOS_POLICY = [
    ('10.0.0.1', 300, 0, 'HIGH',   20000000, 50000000),
    ('10.0.0.3', 200, 1, 'MEDIUM', 10000000, 30000000),
    ('10.0.0.2', 100, 2, 'LOW',     5000000, 15000000),
]


def run(cmd):
    """Execute a shell command, return stdout."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip()


def setup_qos_queues(port_name):
    """
    Create 3 HTB priority queues on the bottleneck port using ovs-vsctl.
    This is the management-plane configuration — identical to what
    a Ryu/POX controller would configure via OpenFlow queue messages.
    """
    info('\n*** [QoS Setup] Creating HTB queues on ' + port_name + '\n')

    # Destroy any leftover QoS config
    subprocess.run('ovs-vsctl -- --all destroy QoS -- --all destroy Queue',
                   shell=True, capture_output=True)
    time.sleep(1)

    cmd = (
        f'ovs-vsctl set port {port_name} qos=@qos -- '
        f'--id=@qos   create QoS  type=linux-htb queues=0=@q0,1=@q1,2=@q2 -- '
        f'--id=@q0    create Queue other-config:min-rate=20000000 other-config:max-rate=50000000 -- '
        f'--id=@q1    create Queue other-config:min-rate=10000000 other-config:max-rate=30000000 -- '
        f'--id=@q2    create Queue other-config:min-rate=5000000  other-config:max-rate=15000000'
    )
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode == 0:
        info('    Queue 0 (HIGH)   : min=20Mbps  max=50Mbps\n')
        info('    Queue 1 (MEDIUM) : min=10Mbps  max=30Mbps\n')
        info('    Queue 2 (LOW)    : min= 5Mbps  max=15Mbps\n')
        info('*** [QoS Setup] Done\n')
    else:
        info('*** [QoS Setup] ERROR: ' + r.stderr + '\n')


def install_flow_rules(switch, out_port):
    """
    Install OpenFlow match-action rules using ovs-ofctl.

    This IS the controller logic:
      match:  IPv4 + source IP
      action: enqueue to priority queue on bottleneck port

    These are real OpenFlow 1.0 rules — exactly what Ryu/POX
    would install via ofp_flow_mod messages.
    """
    info('\n*** [Controller] Installing OpenFlow flow rules on ' + switch + '\n')

    # Delete any existing flows first
    run(f'ovs-ofctl del-flows {switch}')

    # Install one QoS rule per host
    for src_ip, priority, queue_id, label, _, _ in QOS_POLICY:
        match  = f'priority={priority},ip,nw_src={src_ip}'
        action = f'enqueue:{out_port}:{queue_id}'
        run(f'ovs-ofctl add-flow {switch} "{match},actions={action}"')
        info(f'    [{label:6}] {src_ip} → queue {queue_id}  '
             f'(OF priority {priority}, port {out_port})\n')

    # Table-miss: everything else uses normal MAC learning
    run(f'ovs-ofctl add-flow {switch} "priority=1,actions=normal"')
    info('    [MISS  ] all other traffic → normal forwarding\n')
    info('*** [Controller] Flow rules installed\n')


def get_bottleneck_port(switch):
    """
    Return (of_port_number, port_name) for the s1->s2 link.
    s1 ports: eth1=h1, eth2=h2, eth3=h3, eth4=s2  (last one = bottleneck)
    """
    ports = run(f'ovs-vsctl list-ports {switch}').split('\n')
    ports = [p.strip() for p in ports if p.strip()]
    port_name = ports[-1]          # last added = link to s2
    of_port   = len(ports)         # port number = position in list
    return of_port, port_name


def print_verification(switch):
    """Print installed flows and queue config for demo/screenshot."""
    info('\n══════════════════════════════════════════════════\n')
    info('  VERIFICATION — flow table on ' + switch + '\n')
    info('══════════════════════════════════════════════════\n')
    flows = run(f'ovs-ofctl dump-flows {switch}')
    for line in flows.split('\n'):
        if line.strip():
            info('  ' + line.strip() + '\n')

    info('\n══════════════════════════════════════════════════\n')
    info('  VERIFICATION — QoS queues\n')
    info('══════════════════════════════════════════════════\n')
    queues = run('ovs-vsctl list Queue')
    for line in queues.split('\n'):
        if 'min-rate' in line or 'max-rate' in line or '_uuid' in line:
            info('  ' + line.strip() + '\n')


def create_topology():

    # ── Create network ────────────────────────────────────────────────────────
    net = Mininet(
        controller=Controller,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True
    )

    info('*** Adding controller\n')
    net.addController('c0')

    info('*** Adding switches\n')
    s1 = net.addSwitch('s1', protocols='OpenFlow10')
    s2 = net.addSwitch('s2', protocols='OpenFlow10')

    info('*** Adding hosts\n')
    h1 = net.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
    h2 = net.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
    h3 = net.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
    h4 = net.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')
    h5 = net.addHost('h5', ip='10.0.0.5/24', mac='00:00:00:00:00:05')

    info('*** Adding links\n')
    net.addLink(h1, s1, bw=100, delay='2ms')
    net.addLink(h2, s1, bw=100, delay='2ms')
    net.addLink(h3, s1, bw=100, delay='2ms')
    net.addLink(s1, s2, bw=50,  delay='5ms')   # <-- bottleneck
    net.addLink(s2, h4, bw=100, delay='2ms')
    net.addLink(s2, h5, bw=100, delay='2ms')

    # ── Start ─────────────────────────────────────────────────────────────────
    info('*** Starting network\n')
    net.start()
    time.sleep(3)

    # ── QoS + Flow rules ──────────────────────────────────────────────────────
    of_port, port_name = get_bottleneck_port('s1')
    info(f'*** Bottleneck port: {port_name} (OpenFlow port {of_port})\n')

    setup_qos_queues(port_name)
    install_flow_rules('s1', of_port)
    print_verification('s1')

    # ── Ready ─────────────────────────────────────────────────────────────────
    info('\n')
    info('╔══════════════════════════════════════════════════╗\n')
    info('║         QoS NETWORK READY                       ║\n')
    info('╠══════════════════════════════════════════════════╣\n')
    info('║  h1 = 10.0.0.1  HIGH   priority  (Queue 0)     ║\n')
    info('║  h2 = 10.0.0.2  LOW    priority  (Queue 2)     ║\n')
    info('║  h3 = 10.0.0.3  MEDIUM priority  (Queue 1)     ║\n')
    info('║  h4 = 10.0.0.4  Server                         ║\n')
    info('║  h5 = 10.0.0.5  Monitor                        ║\n')
    info('╠══════════════════════════════════════════════════╣\n')
    info('║  SCENARIO 1:  pingall                           ║\n')
    info('║  SCENARIO 2:  see test_qos.sh                  ║\n')
    info('╚══════════════════════════════════════════════════╝\n')
    info('\n')

    CLI(net)

    # ── Cleanup ───────────────────────────────────────────────────────────────
    info('*** Cleaning up\n')
    subprocess.run('ovs-vsctl -- --all destroy QoS -- --all destroy Queue',
                   shell=True, capture_output=True)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    create_topology()
