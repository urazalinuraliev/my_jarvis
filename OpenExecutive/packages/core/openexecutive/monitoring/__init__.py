"""External-condition monitoring layer.

Polls external sources (vendor status pages in PR-A; RSS feeds and stock
prices in PR-B) and emits ``external_signals`` rows. Qualifying signals
are promoted into the existing alerts pipeline so they surface as briefing
proposals via the same path inbound email + Slack alerts use today.

Key entry points:

- ``monitoring.store.initialize_db`` — additive SQLite migration for the
  ``watchlist`` and ``external_signals`` tables. Idempotent; safe to call
  on every boot.
- ``monitoring.pipeline.run_external_monitor_scan`` — one scan pass. Walks
  enabled watchlist rows whose ``last_polled_at`` is stale enough, fires
  the matching adapter, writes signals, promotes those that pass the
  watchlist's ``severity_floor`` (and are not in ``dry_run`` mode) into
  alerts.
- ``monitoring.pipeline.bootstrap_external_monitor_scan`` — idempotent
  seed of the ``external_monitor_scan`` heartbeat row. Called from the
  FastAPI lifespan and the fixture-loader reset path.
"""
