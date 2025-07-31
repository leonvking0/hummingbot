#!/bin/bash

# Script to test BackpackSimpleBuy strategy in headless mode using tmux

echo "Starting BackpackSimpleBuy strategy test in tmux..."

# Kill any existing tmux session with the same name
tmux kill-session -t backpack-test 2>/dev/null

# Create new tmux session and run the strategy
echo "Creating tmux session 'backpack-test'..."
tmux new-session -d -s backpack-test

# Test 1: Run without config (using defaults)
echo "Test 1: Running strategy without config file..."
tmux send-keys -t backpack-test "cd /Users/han/github/hummingbot" C-m
tmux send-keys -t backpack-test "HUMMINGBOT_LOG_LEVEL=DEBUG bin/hummingbot_quickstart.py -p 'YOUR_PASSWORD' -f backpack_simple_buy.py --headless" C-m

echo ""
echo "Strategy is now running in tmux session 'backpack-test'"
echo ""
echo "Useful commands:"
echo "  - View the session:    tmux attach -t backpack-test"
echo "  - Detach from session: Ctrl+B, then D"
echo "  - Kill the session:    tmux kill-session -t backpack-test"
echo "  - List sessions:       tmux ls"
echo ""
echo "The strategy should be placing buy orders for SOL-USDC on Backpack Exchange."
echo "Check logs in logs/ directory for detailed output."