# S48: Dakshitha's notes from testing the deploy (2026-11-04)

1. **Landing:** "A CV you add is stored encrypted and can be deleted" should be one short line. The landing page must not need scrolling on a laptop screen.
2. **Student "Tell Perch about you":** a "Load sample" button, so a student can see what to enter.
3. **"Browse Temple awards" looked empty.** Cause found and fixed: `perch serve` read the empty SQLite file instead of Postgres (commit after 5b214ce). The deploy now lists 360 awards.
4. **Researcher side:** a CV upload on the first visit.
5. **Grant cards** need a lot of refinement. In `s48_notes/grant-card.png` the title shows the record id (`grants_gov:26-519`), which is the same Postgres bug as 3. There is also an empty tag at the top left and a lot of space.
6. **Both sides:** a person can go back, change their details (CV and the rest) and run the scan again.
7. **Many UI alignment issues**, to be found by the QA and UI/UX review passes. `s48_notes/stored-documents.png` shows a stored-documents card with a large empty area.
