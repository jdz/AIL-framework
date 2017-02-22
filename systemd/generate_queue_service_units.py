#!/usr/bin/env python

import os
import sys

from ConfigParser import ConfigParser


def main(root, config):
    for module in config.sections():
        path_prefix = os.path.join(root, "ail-queue-{}".format(module.lower()))
        if config.has_option(module, "subscribe"):
            generate_queue_service_file(path_prefix, "in", module)

        if config.has_option(module, "publish"):
            generate_queue_service_file(path_prefix, "out", module)

        path = os.path.join(root, "ail-module-{}".format(module.lower()))
        generate_module_service_file(path + ".service", module)
        generate_module_path_file(path + ".path", module)


def generate_queue_service_file(path_prefix, direction, module):
    path = path_prefix + "-{}.service".format(direction)
    script = "Queue{}.py".format(direction.capitalize())
    content = """# -*- mode: conf; -*-
[Unit]
AssertPathExists=%h/AIL/AILENV/bin/python
AssertPathExists=%h/AIL/bin/{script}
After=redis-6381.service
BindsTo=redis-6381.service

[Service]
WorkingDirectory=%h/AIL/bin
EnvironmentFile=%h/AIL/systemd/environment
ExecStart=/home/ail/AIL/AILENV/bin/python {script} -c {module}
SyslogIdentifier=ail-{module_lc}-{direction}
Restart=always
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=default.target
""".format(script=script,
           module=module,
           module_lc=module.lower(),
           direction=direction)
    with open(path, "w") as out:
        print("Writing {}".format(path))
        out.write(content)

def generate_module_service_file(path, module):
    content = """# -*- mode: conf; -*-
[Unit]
AssertPathExists=%h/AIL/AILENV/bin/python
AssertPathExists=%h/AIL/bin/{module}.py
After=redis-6381.service
BindsTo=redis-6381.service

[Service]
WorkingDirectory=%h/AIL/bin
EnvironmentFile=%h/AIL/systemd/environment
ExecStart=/home/ail/AIL/AILENV/bin/python {module}.py
SyslogIdentifier=ail-{module_lc}
Restart=always
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=default.target
""".format(module=module, module_lc=module.lower())
    with open(path, "w") as out:
        print("Writing {}".format(path))
        out.write(content)


def generate_module_path_file(path, module):
    content = """# -*- mode: conf; -*-
[Unit]
Description=Restart {module} process when source changes

[Path]
PathModified=%h/AIL/bin/{module}.py

[Install]
WantedBy=default.target
""".format(module=module)
    with open(path, "w") as out:
        print("Writing {}".format(path))
        out.write(content)


if __name__ == "__main__":
    cfg = os.path.join(os.environ['AIL_BIN'], "packages/modules.cfg")
    if not os.path.exists(cfg):
        sys.stderr.write("Configuartion file does not exist: {}".format(cfg))
        sys.exit(1)

    try:
        unit_root = sys.argv[1]
    except IndexError:
        unit_root = os.path.join(os.environ["HOME"], ".config/systemd/user")
    if not os.path.isdir(unit_root):
        sys.stderr.write("systemd user unit root does not exist: {}"
                         .format(unit_root))

    config = ConfigParser()
    config.read(cfg)

    main(unit_root, config)
