# S43 walk: each new check failed first

Each check was run with `scripts/ux_walk.py --plant NAME`, which breaks one thing on purpose with Playwright (no source edits), and had to FAIL. The same check then passes on the real build. Output of the failing runs (1280 px, except the two tag-row plants at 360 px):

```
### badge_on_samples
FAIL  badge_on_every_sample  49 of 50 cards badged
### counts_from_server
FAIL  counts_from_server  15 chips; differ: ['CST', 'CEHD', 'Fox School of Business']
### delete_guard
FAIL  delete_guard  empty disabled False, 'delet' disabled True, 'delete' enabled True
### delete_keyboard
FAIL  delete_takes_focus  |false
FAIL  delete_escape_returns_focus  focus on del-word
### focus_order
FAIL  focus_order_lists  search > level > toggle > tag > card
### guest_banner
FAIL  guest_banner  missing on ['#/funding', '#/samples/student', '#/student']
### no_dead_modules
FAIL  no_dead_modules  requests: ['http://127.0.0.1:8191/mode.js']
### no_sample_public
FAIL  no_sample_in_awards  cards with a sample id or badge: ['sample:sch-0001']
### old_copy
FAIL  old_copy_gone  landing
### tag_row_360
FAIL  tag_row_chips_44  17 chips, shortest 30 px, page overflow 0
FAIL  counts_from_server  15 chips; differ: ['CEHD']
### tag_row_contained
FAIL  tag_row_chips_44  17 chips, shortest 44 px, page overflow 2219
FAIL  tag_row_contained  row scroll 2563 > client 2563, page overflow 2219
```

Notes: tag_row_360 also trips counts_from_server because the plant edits a chip label; guest_banner reports three screens because the hidden banner stays hidden after the plant. Each named check failed.
