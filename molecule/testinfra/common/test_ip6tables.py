import testutils

test_vars = testutils.securedrop_test_vars
testinfra_hosts = [test_vars.app_hostname, test_vars.monitor_hostname]


def test_ipv6_addresses_absent(host):
    """
    Ensure that no IPv6 addresses are assigned to interfaces.
    """
    with host.sudo():
        c = host.check_output("ip -6 addr")
        assert c == ""
