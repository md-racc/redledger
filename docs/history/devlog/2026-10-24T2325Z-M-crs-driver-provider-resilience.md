# 2026-10-24T2325Z — M — CRS driver: provider-outage resilience

blue: `crs_episode_acceptance.py` no longer discards accumulated episode-side failure
evidence when the provider `/users/logs` login fails (observed: sandbox 401 window after
concurrent runs), and retries the login with backoff before failing the run.
