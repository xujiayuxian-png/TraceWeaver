#!/bin/sh
set -eu
python3 /usr/local/bin/gen_certs.py
exec nginx -g 'daemon off;'
