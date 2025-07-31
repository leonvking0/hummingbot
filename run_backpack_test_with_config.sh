#!/bin/bash

# Script to test BackpackSimpleBuy strategy with config file in headless mode

echo "Starting BackpackSimpleBuy strategy test with config file..."

# Kill any existing tmux session with the same name
tmux kill-session -t backpack-config-test 2>/dev/null

# Create new tmux session
echo "Creating tmux session 'backpack-config-test'..."
tmux new-session -d -s backpack-config-test

# Run with config file
echo "Running strategy with config file: backpack_simple_buy_config.yml"
tmux send-keys -t backpack-config-test "cd /Users/han/github/hummingbot" C-m
tmux send-keys -t backpack-config-test "HUMMINGBOT_LOG_LEVEL=DEBUG bin/hummingbot_quickstart.py -p 'YOUR_PASSWORD' -f backpack_simple_buy_config.yml --headless" C-m

echo ""
echo "Strategy is now running in tmux session 'backpack-config-test'"
echo ""
echo "This test uses the config file at: conf/scripts/backpack_simple_buy_config.yml"
echo "Config settings:"
echo "  - Exchange: backpack"
echo "  - Trading pair: SOL-USDC"
echo "  - Order amount: 0.1 SOL"
echo "  - Price discount: 10% below mid price"
echo "  - Order refresh time: 60 seconds"
echo ""
echo "Useful commands:"
echo "  - View the session:    tmux attach -t backpack-config-test"
echo "  - Detach from session: Ctrl+B, then D"
echo "  - Kill the session:    tmux kill-session -t backpack-config-test"
echo "  - List sessions:       tmux ls"