#!/bin/bash
set -e

# Clean up any stale Xvfb lock files
rm -f /tmp/.X99-lock

echo "Starting Xvfb on :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac &
XVFB_PID=$!

sleep 2

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "ERROR: Xvfb failed to start"
    exit 1
fi

export DISPLAY=:99
echo "Xvfb started successfully on DISPLAY=:99"

echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
