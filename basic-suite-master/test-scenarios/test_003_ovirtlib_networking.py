#
# Copyright oVirt Authors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# -*- coding: utf-8 -*-
#
from __future__ import absolute_import

import ipaddress

import pytest

from ovirtsdk4.types import Bonding, HostNic, Option

from ost_utils import network_utils
from ost_utils import test_utils
from ost_utils import utils

from ost_utils.ovirtlib import clusterlib
from ost_utils.ovirtlib import datacenterlib
from ost_utils.ovirtlib import hostlib
from ost_utils.ovirtlib import netattachlib
from ost_utils.ovirtlib import netlib
from ost_utils.ovirtlib import system as systemlib

# DC/Cluster
DC_NAME = 'test-dc'
CLUSTER_NAME = 'test-cluster'

# Networks
VM_NETWORK = u'VM Network with a very long name and עברית'
VM_NETWORK_IPv4_ADDR = '192.0.2.{}'
VM_NETWORK_IPv4_MASK = '255.255.255.0'
VM_NETWORK_IPv6_ADDR = '2001:0db8:85a3:0000:0000:8a2e:0370:733{}'
VM_NETWORK_IPv6_MASK = '64'
VM_NETWORK_VLAN_ID = 100

MIGRATION_NETWORK = 'Migration_Net'  # MTU 9000

BOND_NAME = 'bond_fancy0'
ETH0 = 'eth0'

MIGRATION_NETWORK_IPv4_ADDR = '192.0.3.{}'
MIGRATION_NETWORK_IPv4_MASK = '255.255.255.0'
MIGRATION_NETWORK_IPv6_ADDR = '1001:0db8:85a3:0000:0000:574c:14ea:0a0{}'
MIGRATION_NETWORK_IPv6_MASK = '64'


def _attachment_data(network, nic_name, seed):
    return netattachlib.NetworkAttachmentData(
        network,
        nic_name,
        (
            netattachlib.StaticIpv4Assignment(
                VM_NETWORK_IPv4_ADDR.format(int(seed) + 1),
                VM_NETWORK_IPv4_MASK,
            ),
            netattachlib.StaticIpv6Assignment(
                VM_NETWORK_IPv6_ADDR.format(int(seed) + 1),
                VM_NETWORK_IPv6_MASK,
            ),
        ),
    )


def _assert_expected_ips(host, nic_name, seed):
    host_nic = hostlib.HostNic(host)
    host_nic.import_by_name(f'{nic_name}.{VM_NETWORK_VLAN_ID}')
    assert ipaddress.ip_address(host_nic.ip4_address) == ipaddress.ip_address(
        VM_NETWORK_IPv4_ADDR.format(int(seed) + 1)
    )

    assert ipaddress.ip_address(host_nic.ip6_address) == ipaddress.ip_address(
        VM_NETWORK_IPv6_ADDR.format(int(seed) + 1)
    )


def test_attach_vm_network_to_host_0_static_config(host0, vm_network):
    attach_data = _attachment_data(vm_network, ETH0, host0.name[-1])
    host0.setup_networks((attach_data,))
    _assert_expected_ips(host0, ETH0, host0.name[-1])


def test_modify_host_0_ip_to_dhcp(host0, vm_network):
    attach_data = netattachlib.NetworkAttachmentData(
        vm_network, ETH0, (netattachlib.IPV4_DHCP, netattachlib.IPV6_POLY_DHCP_AUTOCONF)
    )
    host0.setup_networks((attach_data,))

    # TODO: once the VLANs/dnsmasq issue is resolved,
    # (https://github.com/lago-project/lago/issues/375)
    # verify ip configuration.


def test_detach_vm_network_from_host(host0, vm_network, vm_cluster_network):
    vm_cluster_network.update(required=False)
    host0.remove_networks((vm_network,))
    assert not host0.are_networks_attached((vm_network,))


def test_bond_nics(host0, host1, engine_api, bonding_network_name, backend, migration_network):
    engine = engine_api.system_service()

    def _bond_nics(number, host):
        slaves = [HostNic(name=nic) for nic in backend.ifaces_for(host.name, bonding_network_name)]

        options = [
            Option(name='mode', value='active-backup'),
            Option(name='miimon', value='200'),
        ]

        bond = HostNic(name=BOND_NAME, bonding=Bonding(slaves=slaves, options=options))

        ip_configuration = network_utils.create_static_ip_configuration(
            MIGRATION_NETWORK_IPv4_ADDR.format(number),
            MIGRATION_NETWORK_IPv4_MASK,
            MIGRATION_NETWORK_IPv6_ADDR.format(number),
            MIGRATION_NETWORK_IPv6_MASK,
        )

        host_service = engine.hosts_service().host_service(id=host.id)
        network_utils.attach_network_to_host(
            host_service,
            BOND_NAME,
            MIGRATION_NETWORK,
            ip_configuration,
            [bond],
        )

    hosts = test_utils.hosts_in_cluster_v4(engine, CLUSTER_NAME)
    utils.invoke_in_parallel(_bond_nics, list(range(1, len(hosts) + 1)), hosts)

    for host in host0, host1:
        attachment_data = host.get_attachment_data_for_networks((migration_network,))
        assert attachment_data
        host_nic = hostlib.HostNic(host)
        host_nic.import_by_id(next(iter(attachment_data)).nic_id)
        assert host_nic.name == BOND_NAME


def test_verify_interhost_connectivity_ipv4(ansible_host0):
    ansible_host0.shell('ping -c 1 {}'.format(MIGRATION_NETWORK_IPv4_ADDR.format(2)))


def test_verify_interhost_connectivity_ipv6(ansible_host0):
    ansible_host0.shell('ping -c 1 -6 {}'.format(MIGRATION_NETWORK_IPv6_ADDR.format(2)))


def test_remove_bonding(engine_api, host0, host1, migration_network, migration_cluster_network):
    engine = engine_api.system_service()

    def _remove_bonding(host):
        host_service = engine.hosts_service().host_service(id=host.id)
        network_utils.detach_network_from_host(engine, host_service, MIGRATION_NETWORK, BOND_NAME)

    migration_cluster_network.update(required=False)
    utils.invoke_in_parallel(_remove_bonding, test_utils.hosts_in_cluster_v4(engine, CLUSTER_NAME))
    for host in host0, host1:
        assert not host.are_networks_attached((migration_network,))


def test_attach_vm_network_to_both_hosts_static_config(host0, host1, vm_network):
    # preparation for 004 and 006
    for host in (host0, host1):
        attach_data = _attachment_data(vm_network, ETH0, host.name[-1])
        host.setup_networks((attach_data,))
        _assert_expected_ips(host, ETH0, host.name[-1])


@pytest.fixture(scope='module')
def sdk_system(engine_api):
    sdk_system = systemlib.SDKSystemRoot()
    sdk_system.import_conn(engine_api)
    return sdk_system


@pytest.fixture(scope='module')
def data_center(sdk_system):
    dc = datacenterlib.DataCenter(sdk_system)
    dc.import_by_name(DC_NAME)
    return dc


@pytest.fixture(scope='module')
def test_cluster(sdk_system):
    cl = clusterlib.Cluster(sdk_system)
    cl.import_by_name(CLUSTER_NAME)
    return cl


@pytest.fixture(scope='module')
def host0(sdk_system, host0_hostname):
    host = hostlib.Host(sdk_system)
    host.import_by_name(host0_hostname)
    return host


@pytest.fixture(scope='module')
def host1(sdk_system, host1_hostname):
    host = hostlib.Host(sdk_system)
    host.import_by_name(host1_hostname)
    return host


@pytest.fixture(scope='module')
def vm_network(data_center):
    vm_network = netlib.Network(data_center)
    vm_network.import_by_name(VM_NETWORK)
    return vm_network


@pytest.fixture(scope='module')
def migration_network(data_center):
    migration_network = netlib.Network(data_center)
    migration_network.import_by_name(MIGRATION_NETWORK)
    return migration_network


@pytest.fixture(scope='module')
def vm_cluster_network(test_cluster):
    vm_cluster_network = clusterlib.ClusterNetwork(test_cluster)
    vm_cluster_network.import_by_name(VM_NETWORK)
    return vm_cluster_network


@pytest.fixture(scope='module')
def migration_cluster_network(test_cluster):
    migration_cluster_network = clusterlib.ClusterNetwork(test_cluster)
    migration_cluster_network.import_by_name(MIGRATION_NETWORK)
    return migration_cluster_network