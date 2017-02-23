#!/usr/bin/env python2
# -*-coding:UTF-8 -*

'''
    Flask functions and routes for the dashboard page
'''
import json

import datetime
import time
import flask
from flask import Flask, render_template, jsonify, request

# ============ VARIABLES ============
import Flask_config

app = Flask_config.app
cfg = Flask_config.cfg
r_serv = Flask_config.r_serv
r_serv_log = Flask_config.r_serv_log
# ============ FUNCTIONS ============

def event_stream():
    pubsub = r_serv_log.pubsub()
    pubsub.psubscribe("Script" + '.*')
    for msg in pubsub.listen():
        level = msg['channel'].split('.')[1]
        if msg['type'] == 'pmessage' and level != "DEBUG":
            yield 'data: %s\n\n' % json.dumps(msg)

def get_queues(r):
    # We may want to put the llen in a pipeline to do only one query.
    newData = []
    now = int(time.mktime(datetime.datetime.now().timetuple()))
    for queue, card in r.hgetall("queues").iteritems():
        try:
            card = int(card)
        except ValueError:
            card = -1

        key = "MODULE_" + queue + "_"
        keySet = "MODULE_TYPE_" + queue

        for moduleNum in r.smembers(keySet):
            value = r.get(key + str(moduleNum))
            if not value:
                continue

            timestamp, path = value.split(", ")
            seconds = now - int(timestamp)
            newData.append((queue, card, seconds, moduleNum))

    return newData

# ============ ROUTES ============

@app.route("/_logs")
def logs():
    return flask.Response(event_stream(), mimetype="text/event-stream")


@app.route("/_stuff", methods=['GET'])
def stuff():
    return jsonify(row1=get_queues(r_serv))


@app.route("/")
def index():
    default_minute = cfg.get("Flask", "minute_processed_paste")
    threshold_stucked_module = cfg.getint("Module_ModuleInformation", "threshold_stucked_module")
    return render_template("index.html", default_minute = default_minute, threshold_stucked_module=threshold_stucked_module)
