#!/bin/sh
# Install or update the agent. Run with sudo from the folder holding these files.
# agent.json (url + token) is only needed the first time; it becomes /etc/homepage-agent.json.
set -e
cd "$(dirname "$0")"
install -Dm644 agent.py /usr/local/lib/homepage-agent/agent.py
if [ -f agent.json ]; then
    install -m600 -o root -g root agent.json /etc/homepage-agent.json
    rm -f agent.json
fi
install -m644 homepage-agent.service /etc/systemd/system/homepage-agent.service
systemctl daemon-reload
systemctl enable homepage-agent
systemctl restart homepage-agent
systemctl --no-pager --lines=3 status homepage-agent
