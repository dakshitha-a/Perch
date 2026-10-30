# Monitoring, shelved (S23)

The weekly watch (S16) re-ran a brief for each watched researcher, compared it with the last run and drafted an email when an award was about to end or a new opportunity entered the top 10. It needs to know who to watch, and since S23 Perch keeps nothing about its users, so it is shelved until a user system exists.

What is here:

- `monitor.py`: the Grants.gov delta refresh, the two triggers, the diff and the code-written draft. It still imports from `perch` and is checked to import by `tests/test_shelved.py`.
- `web/watch.js`: the What changed screen (`#/changes`).
- `deploy/`: the Monday 06:00 systemd timer and its service for the demo.
- `tests/test_monitor.py`: its tests, skipped and outside pytest's `testpaths`.

What was removed, and is in the git history before S23: the `GET /watch` route in `perch/api.py`, the `perch monitor` command in `perch/cli.py`, the `#/changes` route and the What changed link in `web/app.js`, the Help step in `web/help.js`, and the `demo-monitor` target and timer lines in the `Makefile`.

To reconnect it once users have accounts:

1. Watch a user's chosen researchers, stored with their consent, instead of `PERCH_WATCH`.
2. `monitor.run` stores `Brief`, `Lead` and `Digest` records through `BriefService`; give it a store the user owns, because sessions keep nothing.
3. Move the module back to `perch/monitor.py`, the screen to `web/`, the units to `deploy/systemd/demo/`, and the tests to `tests/`; drop the skip mark.
4. Bring back the route, the command, the link and the Help step from history, and the draft stays a draft: nothing is sent (standing rule 7).
