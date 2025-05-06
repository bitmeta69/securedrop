"""
Import all of the test_grsecurity suite, but clear testinfra_hosts so that
running "py.test test_grsecurity_local.py" will run the test suite locally.
"""

from common.test_grsecurity import *  # noqa: F403

testinfra_hosts = [None]
