"""Indian market support: NSE / BSE equities and indices, equity F&O, MCX commodities
and NSE currency derivatives.

Kept import-free so ``symbol_utils`` can lazily import ``india.instruments``
without pulling in the network-backed modules (``fno``, ``cash_market``).
"""
