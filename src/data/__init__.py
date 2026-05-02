"""
src.data — Phase 3.5+ data adapters.

This package hosts thin adapters that supply the redesigned UI with
data shapes it expects (e.g. MarketStrip, ChipsKpi). Existing data
fetching pipelines under src/fetcher/, src/storage/, src/news/ remain
authoritative; modules here either re-shape that data or stub it
deterministically when no live source exists yet.
"""
