#!/usr/bin/env bash
echo 'Running migrations'
alembic upgrade head

echo 'Starting swipe backend'
python main.py
