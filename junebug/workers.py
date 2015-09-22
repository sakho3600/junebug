import json
import logging
from twisted.internet.defer import inlineCallbacks
import treq
from vumi.application.base import ApplicationConfig, ApplicationWorker
from vumi.config import ConfigDict, ConfigInt, ConfigText
from vumi.message import JSONMessageEncoder
from vumi.persist.txredis_manager import TxRedisManager

from junebug.utils import api_from_message
from junebug.stores import InboundMessageStore, OutboundMessageStore


class MessageForwardingConfig(ApplicationConfig):
    '''Config for MessageForwardingWorker application worker'''

    mo_message_url = ConfigText(
        "The URL to send HTTP POST requests to for MO messages",
        required=True, static=True)

    redis_manager = ConfigDict(
        "Redis config.",
        required=True, static=True)

    inbound_ttl = ConfigInt(
        "Maximum time (in seconds) allowed to reply to messages",
        required=True, static=True)

    outbound_ttl = ConfigInt(
        "Maximum time (in seconds) allowed for events to arrive for messages",
        required=True, static=True)


class MessageForwardingWorker(ApplicationWorker):
    '''This application worker consumes vumi messages placed on a configured
    amqp queue, and sends them as HTTP requests with a JSON body to a
    configured URL'''
    CONFIG_CLASS = MessageForwardingConfig

    @inlineCallbacks
    def setup_application(self):
        self.redis = yield TxRedisManager.from_config(
            self.config['redis_manager'])

        self.inbounds = InboundMessageStore(
            self.redis, self.config['inbound_ttl'])

        self.outbounds = OutboundMessageStore(
            self.redis, self.config['outbound_ttl'])

    @inlineCallbacks
    def teardown_application(self):
        yield self.redis.close_manager()

    @inlineCallbacks
    def consume_user_message(self, message):
        '''Sends the vumi message as an HTTP request to the configured URL'''
        config = yield self.get_config(message)
        yield self.inbounds.store_vumi_message(config.transport_name, message)
        url = config.mo_message_url.encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
        }
        msg = json.dumps(
            api_from_message(message), cls=JSONMessageEncoder)
        resp = yield treq.post(url, data=msg, headers=headers)
        if resp.code < 200 or resp.code >= 300:
            logging.exception(
                'Error sending message, received HTTP code %r with body %r. '
                'Message: %r' % (resp.code, (yield resp.content()), msg))
