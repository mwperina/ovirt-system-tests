#
# Copyright oVirt Authors
# SPDX-License-Identifier: GPL-2.0-or-later
#
#

import contextlib
import logging

from ost_utils.selenium.grid import CHROME_CONTAINER_IMAGE
from ost_utils.selenium.grid import FIREFOX_CONTAINER_IMAGE
from ost_utils.selenium.grid import HUB_CONTAINER_IMAGE
from ost_utils.selenium.grid import common
from ost_utils.shell import shell


HUB_PORT = 4444
LOGGER = logging.getLogger(__name__)
NETWORK_NAME = 'grid'


def _log_issues(hub_name, node_names):
    LOGGER.error("Hub logs: \n%s" % shell(["docker", "logs", hub_name]))
    for name in node_names:
        LOGGER.error(
            "Node %s logs: \n%s" % (name, shell(["docker", "logs", name]))
        )


def _get_ip(name):
    ip = shell(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            name,
        ]
    ).strip()

    if ip == "":
        raise RuntimeError(
            (
                "Could not get ip address of container. "
                "See previous messages for probable docker failure"
            )
        )

    return ip


@contextlib.contextmanager
def _network(network_name):
    shell(["docker", "network", "create", network_name])

    try:
        yield
    finally:
        shell(["docker", "network", "rm", network_name])


@contextlib.contextmanager
def _hub(image, port, network_name):
    name = shell(
        [
            "docker",
            "run",
            "-d",
            "-p",
            "{0}:{0}".format(port),
            "--net",
            network_name,
            image,
        ]
    ).strip()

    try:
        yield name, _get_ip(name)
    finally:
        shell(["docker", "rm", "-f", name])


@contextlib.contextmanager
def _nodes(images, hub_ip, hub_port, network_name, engine_dns_entry):
    names = []

    for image in images:
        name = shell(
            [
                "docker",
                "run",
                "-d",
                "--add-host={}".format(engine_dns_entry),
                "--net",
                network_name,
                "-e",
                "HUB_HOST={}".format(hub_ip),
                "-e",
                "HUB_PORT={}".format(hub_port),
                "-v",
                "/dev/shm:/dev/shm",
                image,
            ]
        ).strip()

        names.append(name)

    try:
        yield names
    finally:
        for name in names:
            shell(["docker", "rm", "-f", name])


@contextlib.contextmanager
def grid(
    engine_fqdn,
    engine_ip,
    node_images=None,
    hub_image=HUB_CONTAINER_IMAGE,
    hub_port=HUB_PORT,
    network_name=NETWORK_NAME,
):
    if node_images is None:
        node_images = [CHROME_CONTAINER_IMAGE, FIREFOX_CONTAINER_IMAGE]

    engine_dns_entry = "{}:{}".format(engine_fqdn, engine_ip)

    with common.http_proxy_disabled():
        with _network(network_name):
            with _hub(hub_image, hub_port, network_name) as (hub_name, hub_ip):
                with _nodes(
                    node_images,
                    hub_ip,
                    hub_port,
                    network_name,
                    engine_dns_entry,
                ) as node_names:
                    url = common.GRID_URL_TEMPLATE.format(hub_ip, hub_port)
                    try:
                        common.grid_health_check(url, len(node_images))
                    except RuntimeError:
                        _log_issues(hub_name, node_names)
                        raise
                    yield url