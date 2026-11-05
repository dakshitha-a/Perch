# Screenshots (retaken for the v1 build, S52, extended in S55)

Taken from the running v1 app with `scripts/screenshots.py` (Playwright). The researcher screens come from the SYNTHETIC demo researcher account's existing brief for the researcher shown as PI-1; every JSON answer has real names swapped for the alias and the text of each screen is checked for a real name before the image is saved. The student screens come from the SYNTHETIC demo student account, invented text only. The guest pages show no person. No real researcher name appears; the only people's names are in award titles copied from Temple's public pages.

- **File names:** `<width>-<scheme>-<n>-<name>.png`, where width is `wide` (1280 by 800) or `phone` (390 by 844 at 2x), and scheme is `light` or `dark`.
- **Count:** 19 screens, each in four versions, 76 images.
- **Retake:** `scripts/screenshots.py --base <url> --env-file <file with the DEMO_* logins>`. Add `--only 13 14` to retake some screens.
- **Staged states:** screen 18 holds the Scout request open so the glow shows. Screen 15 adds the "You chose" words to the brief's answer, because the account's picks were reset when the images were taken. Everything else is the app as served.
- **Figures:** the architecture, roadmap and cost figures are rendered by `scripts/render_figures.py` into `docs/architecture/<name>-light.png` and `-dark.png`.

In the lines below, `{wide,phone}-{light,dark}-N-*.png` means all four versions of screen N.

- **1. Landing:** the front page with the Student and Researcher choice and the trust notes.
- **2. Temple awards:** the guest list of Temple scholarships and fellowships with its school filters.
- **3. Research funding:** the guest list of open research calls with search and sort.
- **4. Help:** the visual guide that explains the steps for a researcher and a student.
- **5. Researcher brief:** the top of the routes list for the example researcher, shown as PI-1.
- **6. Why it fits:** the first card with its Why it fits fold open and the cited papers below it.
- **7. Evidence:** one card with its evidence panel open, showing the record fields.
- **8. Temple internal:** the Temple internal tab with the university's own calls for faculty.
- **9. Compare:** two kept leads side by side, every cell copied from its record.
- **10. Scout, researcher:** the Ask Scout tab with its greeting and example questions.
- **11. Student brief:** the top of the options list for the SYNTHETIC student.
- **12. Student rule lines:** one student card open, showing the eligibility rule lines and the model's wording.
- **13. Student start with picks:** the start form with the stored CV and the optional citizenship and state picks.
- **14. Researcher start with picks:** after a researcher is chosen, the folded "Citizenship and state (optional)" section.
- **15. What the rules read from your CV:** the Read tab, with the fields read by code and the "You chose" line.
- **16. Citizenship note on a card:** the Gilman scholarship card, whose citizenship line names the page where the rule was found.
- **17. Scout with Ask and Clear:** the Scout tab with a cited answer, the question box, Ask and Clear.
- **18. Scout working:** the question box glows while Scout works.
- **19. Conversation cleared:** the line "Conversation cleared. Undo" after Clear.
