"""The channels domain: the bridge between external sales channels and the Order Engine.

ADR-029 §2. The S10 tables still live in `app/models/channel_hub.py` and
`app/models/channel_catalog.py`; code born for S10.1 is born here (§1.2), and the
flat `channel_hub_service` moves in as each step of the S10.1 proposal lands.

Kept free of imports on purpose, like `finance/bridge`: nothing heavier than a
docstring runs when a submodule is imported.
"""
