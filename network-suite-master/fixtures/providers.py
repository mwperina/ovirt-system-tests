#
# Copyright 2018 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#
import os
import pytest
import shade
import yaml

from lib.providerlib import OpenStackImageProviders
from lib.providerlib import OpenStackNetworkProvider


OPENSTACK_AUTH_URL = 'https://{}:35357/v2.0'
OPENSTACK_USERNAME = 'admin@internal'
OVIRT_IMAGE_REPO_NAME = 'ovirt-image-repository'
OVIRT_IMAGE_REPO_URL = 'http://glance.ovirt.org:9292/'
OPENSTACK_CLIENT_CONFIG_FILE = 'clouds.yml'
DEFAULT_CLOUD = 'ovirt'
DEFAULT_OVN_PROVIDER_NAME = 'ovirt-provider-ovn'
DEFAULT_OVN_NETWORK_NAME = 'default_network_name'
DEFAULT_OVN_SUBNET_CIDR = '10.0.0.0/24'
DEFAULT_OVN_SUBNET_NAME = 'default_subnet_name'
DEFAULT_OVN_SUBNET_GW = '10.0.0.3'


@pytest.fixture(scope='session')
def ovirt_image_repo(system):
    openstack_image_providers = OpenStackImageProviders(system)
    if openstack_image_providers.is_provider_available(OVIRT_IMAGE_REPO_NAME):
        openstack_image_providers.import_by_name(OVIRT_IMAGE_REPO_NAME)
    else:
        openstack_image_providers.create(name=OVIRT_IMAGE_REPO_NAME,
                                         url=OVIRT_IMAGE_REPO_URL,
                                         requires_authentication=False)
        openstack_image_providers.wait_until_available()


@pytest.fixture(scope='session')
def openstack_client_config(engine):
    cloud_config = {
        'clouds': {
            'ovirt': {
                'auth': {
                    'auth_url': OPENSTACK_AUTH_URL.format(engine.ip()),
                    'username': OPENSTACK_USERNAME,
                    'password': engine.metadata['ovirt-engine-password']
                },
                'verify': False
            }
        }
    }
    os_client_config_file_path = os.path.join(
        os.environ.get('SUITE'), OPENSTACK_CLIENT_CONFIG_FILE
    )
    with open(os_client_config_file_path, 'w') as cloud_config_file:
        yaml.dump(cloud_config, cloud_config_file, default_flow_style=False)

    original_os_client_config_file = os.environ.get('OS_CLIENT_CONFIG_FILE')
    os.environ['OS_CLIENT_CONFIG_FILE'] = os_client_config_file_path
    yield
    if original_os_client_config_file is not None:
        os.environ['OS_CLIENT_CONFIG_FILE'] = original_os_client_config_file
    else:
        del os.environ['OS_CLIENT_CONFIG_FILE']


@pytest.fixture(scope='session')
def default_ovn_provider(system):
    openstack_network_provider = OpenStackNetworkProvider(system)
    openstack_network_provider.import_by_name(DEFAULT_OVN_PROVIDER_NAME)
    with openstack_network_provider.disable_auto_sync():
        yield openstack_network_provider


@pytest.fixture(scope='session')
def ovn_network(openstack_client_config, default_ovn_provider):
    network_name = DEFAULT_OVN_NETWORK_NAME
    cloud = shade.openstack_cloud(cloud=DEFAULT_CLOUD)
    network = cloud.create_network(network_name)
    try:
        subnet = cloud.create_subnet(
            network.id,
            cidr=DEFAULT_OVN_SUBNET_CIDR,
            subnet_name=DEFAULT_OVN_SUBNET_NAME,
            enable_dhcp=True,
            gateway_ip=DEFAULT_OVN_SUBNET_GW,
        )
        yield network
        cloud.delete_subnet(subnet.id)
    finally:
        cloud.delete_network(network.id)
