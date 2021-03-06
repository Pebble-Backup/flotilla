import unittest
from mock import patch
from click import BadParameter

from flotilla.cli.service import configure_service, get_updates, \
    validate_health_check

ENVIRONMENT = 'develop'
REGIONS = ('us-east-1', 'us-west-2')
SERVICE = 'test'

ELB_SCHEME = 'internal'
DNS = 'test.test.com'
HEALTH_CHECK = 'HTTP:9200/'
INSTANCE_TYPE = 't2.nano'
NO_PROVISION = True
INSTANCE_MIN = 1
INSTANCE_MAX = 2
KMS_KEY = '5901dc99-0a0e-480a-a67f-559347ff2c64'
COREOS_CHANNEL = 'alpha'
COREOS_VERSION = 'current'


class TestService(unittest.TestCase):
    def test_get_updates_noop(self):
        updates = get_updates(None, None, None, None, None, None, None, None,
                              None, None, (), ())
        self.assertEquals(len(updates), 0)

    def test_get_updates_basic(self):
        updates = get_updates(ELB_SCHEME, DNS, HEALTH_CHECK, INSTANCE_TYPE,
                              NO_PROVISION, INSTANCE_MIN, INSTANCE_MAX, KMS_KEY,
                              COREOS_CHANNEL, COREOS_VERSION, None, None)
        self.assertEquals(len(updates), 10)

    def test_get_updates_public_ports(self):
        updates = get_updates(None, None, None, None, None, None, None, None,
                              None, None, ('80-http', '9200-http'), None)
        self.assertEquals(len(updates), 1)
        ports = updates['public_ports']
        self.assertEquals(len(ports), 2)
        self.assertEquals(ports[80], 'HTTP')
        self.assertEquals(ports[9200], 'HTTP')

    def test_get_updates_public_ports_invalid(self):
        updates = get_updates(None, None, None, None, None, None, None, None,
                              None, None, ('swag',), None)
        self.assertEquals(len(updates), 0)

    def test_get_updates_private_ports(self):
        updates = get_updates(None, None, None, None, None, None, None, None,
                              None, None, None, ('9300-tcp',))
        self.assertEquals(len(updates), 1)
        ports = updates['private_ports']
        self.assertEquals(len(ports), 1)
        self.assertEquals(ports[9300], ['TCP'])

    def test_get_updates_private_ports_invalid(self):
        updates = get_updates(None, None, None, None, None, None, None, None,
                              None, None, None, ('swag',))
        self.assertEquals(len(updates), 0)

    @patch('flotilla.cli.service.DynamoDbTables')
    @patch('boto.dynamodb2.connect_to_region')
    @patch('boto.kms.connect_to_region')
    def test_configure_service(self, kms, dynamo, tables):
        configure_service(ENVIRONMENT, REGIONS, SERVICE, {})
        self.assertEquals(kms.call_count, len(REGIONS))
        self.assertEquals(dynamo.call_count, len(REGIONS))

    def test_validate_health_check_invalid(self):
        self.assert_invalid_health_check('10')

    def test_validate_health_check_badproto(self):
        self.assert_invalid_health_check('WS:443/')

    def test_validate_health_check_no_path(self):
        self.assert_invalid_health_check('HTTP:80')

    def test_validate_health_check_tcp(self):
        health_check = validate_health_check(None, None, 'TCP:6379')
        self.assertEquals('TCP:6379', health_check)

    def test_validate_health_check_http(self):
        health_check = validate_health_check(None, None, 'HTTP:80/ping')
        self.assertEquals('HTTP:80/ping', health_check)

    def test_validate_health_check_empty(self):
        health_check = validate_health_check(None, None, None)
        self.assertEquals(None, health_check)

    def assert_invalid_health_check(self, check):
        self.assertRaises(BadParameter, validate_health_check, None, None,
                          check)
