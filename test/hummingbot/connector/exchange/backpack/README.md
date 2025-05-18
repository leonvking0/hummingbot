# Backpack Connector Tests

Unit tests for the Backpack exchange connector live in this directory.

To run the test suite:

```bash
pytest test/hummingbot/connector/exchange/backpack
```

Set the environment variables `BACKPACK_API_KEY` and `BACKPACK_SECRET_KEY` if you
intend to run integration tests or the manual QA script.

A simple manual QA strategy is available in
`scripts/community/backpack_testnet_qa.py`. Run it with:

```bash
bin/hummingbot.py run scripts/community/backpack_testnet_qa.py
```

The strategy will place a single market order on the configured trading pair and
exit after completion.

