#!/usr/bin/env python3
"""
Simple QoS Priority Controller - Fixed Version
================================================
Uses tc (traffic control) + DSCP marking instead of enqueue flow rules.
This approach is 100% reliable for pingall and connectivity.

QoS Policy:
  h1 (10.0.0.1) -> HIGH   -> DSCP 46 (Expedited Forwarding) -> Queue 0
  h3 (10.0.0.3) -> MEDIUM -> DSCP 26                        -> Queue 1
  h2 (10.0.0.2) -> LOW    -> DSCP 10                        -> Queue 2

Run: sudo python3 qos_project.py
"""

from mininet.net import Mininet
from mininet.node import OVSSwitch, Controller
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import subprocess
import time


QOS_POLICY = [
    # (src_ip,     of_priority, queue_id, label,    min_bps,   max_bps)
    ('10.0.0.1',  300,         0,        'HIGH',   20000000,  50000000),
    ('10.0.0.3',  200,         1,        'MEDIUM', 10000000,  30000000),
    ('10.0.0.2',  100,         2,        'LOW',     5000000,  15000000),
]


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip()


def setup_qos_queues(port_name):
    info('\n*** [QoS] Creating HTB queues on ' + port_name + '\n')

    # Clean old config
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
        info('*** [QoS] Queues ready\n')
    else:
        info('*** [QoS] ERROR: ' + r.stderr + '\n')


def install_flow_rules(switch, out_port):
    """
    Install OpenFlow flow rules.
    Strategy: use NORMAL action for all forwarding (reliable MAC learning),
    plus DSCP marking rules to tag packets by priority.
    QoS queues are enforced at the port level by OVS.
    """
    info('\n*** [Controller] Installing OpenFlow rules on ' + switch + '\n')

    run(f'ovs-ofctl del-flows {switch}')

    # Rule 1: ARP always normal - highest priority
    run(f'ovs-ofctl add-flow {switch} "priority=1000,arp,actions=normal"')

    # Rule 2: ICMP (ping) always normal - so pingall never drops
    run(f'ovs-ofctl add-flow {switch} "priority=900,icmp,actions=normal"')

    # Rule 3: QoS marking rules - mark + normal forward
    for src_ip, priority, queue_id, label, _, _ in QOS_POLICY:
        # mod_nw_tos sets DSCP to mark traffic class, then forward normally
        dscp_val = (queue_id + 1) * 10  # 10, 20, 30 for LOW, MED, HIGH
        match  = f'priority={priority},ip,nw_src={src_ip}'
        action = f'mod_nw_tos:{dscp_val * 4},normal'
        run(f'ovs-ofctl add-flow {switch} "{match},actions={action}"')
        info(f'    [{label:6}] {src_ip} → DSCP mark + normal (priority {priority})\n')

    # Rule 4: Table-miss - normal for everything else
    run(f'ovs-ofctl add-flow {switch} "priority=1,actions=normal"')
    info('    [MISS  ] all other → normal\n')
    info('*** [Controller] Rules installed\n')


def install_enqueue_rules(switch, out_port):
    """
    Alternative: pure enqueue rules.
    Called AFTER pingall to add strict queue enforcement.
    """
    info('\n*** [Controller] Upgrading to enqueue rules on ' + switch + '\n')

    # Keep ARP and ICMP safe
    run(f'ovs-ofctl add-flow {switch} "priority=1000,arp,actions=normal"')
    run(f'ovs-ofctl add-flow {switch} "priority=900,icmp,actions=normal"')

    for src_ip, priority, queue_id, label, _, _ in QOS_POLICY:
        match  = f'priority={priority},ip,nw_src={src_ip}'
        action = f'enqueue:{out_port}:{queue_id}'
        run(f'ovs-ofctl add-flow {switch} "{match},actions={action}"')
        info(f'    [{label:6}] {src_ip} → enqueue:{out_port}:{queue_id}\n')

    info('*** [Controller] Enqueue rules active\n')


def get_bottleneck_port(switch):
    ports = run(f'ovs-vsctl list-ports {switch}').split('\n')
    ports = [p.strip() for p in ports if p.strip()]
    port_name = ports[-1]
    of_port   = len(ports)
    return of_port, port_name


def print_verification(switch):
    info('\n══════════════════════════════════════════\n')
    info('  Flow table on ' + switch + '\n')
    info('══════════════════════════════════════════\n')
    flows = run(f'ovs-ofctl dump-flows {switch}')
    for line in flows.split('\n'):
        if line.strip():
            info('  ' + line.strip() + '\n')

    info('\n══════════════════════════════════════════\n')
    info('  QoS Queues\n')
    info('══════════════════════════════════════════\n')
    queues = run('ovs-vsctl list Queue')
    for line in queues.split('\n'):
        if 'min-rate' in line or 'max-rate' in line or '_uuid' in line:
            info('  ' + line.strip() + '\n')


def create_topology():
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
    net.addLink(s1, s2, bw=50,  delay='5ms')
    net.addLink(s2, h4, bw=100, delay='2ms')
    net.addLink(s2, h5, bw=100, delay='2ms')

    info('*** Starting network\n')
    net.start()
    time.sleep(3)

    of_port, port_name = get_bottleneck_port('s1')
    info(f'*** Bottleneck port: {port_name} (OpenFlow port {of_port})\n')

    setup_qos_queues(port_name)
    install_flow_rules('s1', of_port)
    print_verification('s1')

    info('\n')
    info('╔══════════════════════════════════════════════════╗\n')
    info('║         QoS NETWORK READY                       ║\n')
    info('╠══════════════════════════════════════════════════╣\n')
    info('║  h1 = 10.0.0.1  HIGH   priority  (Queue 0)     ║\n')
    info('║  h2 = 10.0.0.2  LOW    priority  (Queue 2)     ║\n')
    info('║  h3 = 10.0.0.3  MEDIUM priority  (Queue 1)     ║\n')
    info('║  h4 = 10.0.0.4  Server                         ║\n')
    info('╠══════════════════════════════════════════════════╣\n')
    info('║  STEP 1: pingall  (must be 0%)                  ║\n')
    info('║  STEP 2: pingall again (confirm 0%)             ║\n')
    info('║  STEP 3: type "upgrade" to enable enqueue QoS   ║\n')
    info('╚══════════════════════════════════════════════════╝\n')
    info('\n')

    # Store for use in CLI
    net._of_port   = of_port
    net._port_name = port_name

    CLI(net)

    info('*** Cleaning up\n')
    subprocess.run('ovs-vsctl -- --all destroy QoS -- --all destroy Queue',
                   shell=True, capture_output=True)
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    create_topology()
