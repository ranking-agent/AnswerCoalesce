#!/usr/bin/env bash

# export $(egrep -v '^#' .env | xargs)

# gunicorn --bind 0.0.0.0:6380 -w 1 -k uvicorn.workers.UvicornWorker -t 600 src.server:APP --root-path /1.2

uvicorn --host 0.0.0.0 --port 6380 --workers 1 src.server:APP --root-path /1.2
