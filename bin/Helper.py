#!/usr/bin/env python2
# -*-coding:UTF-8 -*
"""
Queue helper module
============================

This module subscribe to a Publisher stream and put the received messages
into a Redis-list waiting to be popped later by others scripts.

..note:: Module ZMQ_Something_Q and ZMQ_Something are closely bound, always put
the same Subscriber name in both of them.

"""
import redis
import ConfigParser
import os
import errno
import zmq
import time
import datetime
import json


class PubSub(object):

    def __init__(self):
        configfile = os.path.join(os.environ['AIL_BIN'], 'packages/config.cfg')
        if not os.path.exists(configfile):
            raise Exception('Unable to find the configuration file. \
                            Did you set environment variables? \
                            Or activate the virtualenv.')
        self.config = ConfigParser.ConfigParser()
        self.config.read(configfile)
        self.redis_sub = False
        self.zmq_sub = False
        self.subscribers = None
        self.publishers = {'Redis': [], 'ZMQ': []}

    def setup_subscribe(self, conn_name):
        if self.config.has_section(conn_name):
            channel = self.config.get(conn_name, 'channel')
        else:
            channel = conn_name.split('_')[1]
        if conn_name.startswith('Redis'):
            self.redis_sub = True
            r = redis.StrictRedis(
                host=self.config.get('RedisPubSub', 'host'),
                port=self.config.get('RedisPubSub', 'port'),
                db=self.config.get('RedisPubSub', 'db'))
            self.subscribers = r.pubsub(ignore_subscribe_messages=True)
            self.subscribers.psubscribe(channel)
        elif conn_name.startswith('ZMQ'):
            self.zmq_sub = True
            context = zmq.Context()

            self.subscribers = []
            addresses = self.config.get(conn_name, 'address')
            for address in addresses.split(','):
                new_sub = context.socket(zmq.SUB)
                new_sub.connect(address)
                new_sub.setsockopt(zmq.SUBSCRIBE, channel)
                self.subscribers.append(new_sub)

    def setup_publish(self, conn_name):
        if self.config.has_section(conn_name):
            channel = self.config.get(conn_name, 'channel')
        else:
            channel = conn_name.split('_')[1]
        if conn_name.startswith('Redis'):
            r = redis.StrictRedis(host=self.config.get('RedisPubSub', 'host'),
                                  port=self.config.get('RedisPubSub', 'port'),
                                  db=self.config.get('RedisPubSub', 'db'))
            self.publishers['Redis'].append((r, channel))
        elif conn_name.startswith('ZMQ'):
            context = zmq.Context()
            p = context.socket(zmq.PUB)
            p.bind(self.config.get(conn_name, 'address'))
            self.publishers['ZMQ'].append((p, channel))

    def publish(self, message):
        m = json.loads(message)
        channel_message = m.get('channel')
        for p, channel in self.publishers['Redis']:
            if channel_message is None or channel_message == channel:
                p.publish(channel, m['message'])
        for p, channel in self.publishers['ZMQ']:
            if channel_message is None or channel_message == channel:
                p.send('{} {}'.format(channel, m['message']))

    def subscribe(self):
        if self.redis_sub:
            for msg in self.subscribers.listen():
                if msg.get('data', None) is not None:
                    yield msg['data']
        elif self.zmq_sub:
            while True:
                for sub in self.subscribers:
                    try:
                        msg = sub.recv(zmq.NOBLOCK)
                        yield msg.split(' ', 1)[1]
                    except zmq.error.Again as e:
                        time.sleep(0.2)
                        pass
        else:
            raise Exception('No subscribe function defined')


class Process(object):

    def __init__(self, conf_section):
        configfile = os.path.join(os.environ['AIL_BIN'], 'packages/config.cfg')
        if not os.path.exists(configfile):
            raise Exception('Unable to find the configuration file. \
                            Did you set environment variables? \
                            Or activate the virtualenv.')
        modulesfile = os.path.join(
            os.environ['AIL_BIN'],
            'packages/modules.cfg',
        )
        self.config = ConfigParser.ConfigParser()
        self.config.read(configfile)
        self.modules = ConfigParser.ConfigParser()
        self.modules.read(modulesfile)
        self.subscriber_name = conf_section

        self.pubsub = None
        if self.modules.has_section(conf_section):
            self.pubsub = PubSub()
        else:
            raise Exception('Your process has to listen to at least one feed.')
        self.r_temp = redis.StrictRedis(
            host=self.config.get('RedisPubSub', 'host'),
            port=self.config.get('RedisPubSub', 'port'),
            db=self.config.get('RedisPubSub', 'db'))

        self.moduleNum = os.getpid()
        self.clean_up_queues()

    def clean_up_queues(self):
        dead = []

        key = "MODULE_TYPE_" + self.subscriber_name
        for pid in self.r_temp.smembers(key):
            try:
                os.kill(int(pid), 0)
            except OSError as e:
                if e.errno == errno.ESRCH:
                    print("Found dead {} instance: {}".format(
                        self.subscriber_name,
                        pid,
                    ))
                    dead.append(pid)
            except ValueError:
                print("Invalid {} pid: {}".format(self.subscriber_name, pid))

        if dead:
            pipe = self.r_temp.pipeline()
            pipe.srem(key, dead)
            for pid in dead:
                pipe.delete(self.module_queue(pid))
            pipe.execute()

    def module_queue(self, pid=None):
        return "MODULE_{}_{}".format(
            self.subscriber_name,
            pid or self.moduleNum,
        )

    def populate_set_in(self):
        # monoproc
        src = self.modules.get(self.subscriber_name, 'subscribe')
        self.pubsub.setup_subscribe(src)
        for msg in self.pubsub.subscribe():
            in_set = self.subscriber_name + 'in'
            self.r_temp.sadd(in_set, msg)
            self.r_temp.hset('queues', self.subscriber_name,
                             int(self.r_temp.scard(in_set)))

    def get_from_set(self):
        # multiproc
        in_set = self.subscriber_name + 'in'
        self.r_temp.hset('queues', self.subscriber_name,
                         int(self.r_temp.scard(in_set)))
        message = self.r_temp.spop(in_set)
        if message is None:
            return None

        timestamp = int(time.mktime(datetime.datetime.now().timetuple()))
        basename = os.path.basename(message) or "?"
        value = str(timestamp) + ", " + basename
        self.r_temp.set(self.module_queue(), value)
        self.r_temp.sadd(
            "MODULE_TYPE_" + self.subscriber_name,
            str(self.moduleNum),
        )
        return message

    def populate_set_out(self, msg, channel=None):
        # multiproc
        msg = {'message': msg}
        if channel is not None:
            msg.update({'channel': channel})
        self.r_temp.sadd(self.subscriber_name + 'out', json.dumps(msg))

    def publish(self):
        # monoproc
        if not self.modules.has_option(self.subscriber_name, 'publish'):
            return False
        dest = self.modules.get(self.subscriber_name, 'publish')
        # We can have multiple publisher
        for name in dest.split(','):
            self.pubsub.setup_publish(name)
        while True:
            message = self.r_temp.spop(self.subscriber_name + 'out')
            if message is None:
                time.sleep(1)
                continue
            self.pubsub.publish(message)
