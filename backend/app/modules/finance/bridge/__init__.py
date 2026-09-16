"""Delivering payment commands to a paired TEF bridge, and holding its pinpad.

Owns `tef_bridge_commands` and `tef_terminal_occupancy` (migration 097). The
contract is docs/product/proposta-transporte-comandos-bridge.md, revision 3.1.

Kept free of imports on purpose: `app.models` registers these tables by
importing `models`, and anything heavier here would run inside that import.
"""
