"""Causal capability probes for assistant model acceptance.

The provider label never substitutes for a probe: a model is accepted for
the primary assistant role only after it independently passes the text oracle
and the causal-vision oracle over the versioned logo fixture plus its
controlled altered variant.
"""