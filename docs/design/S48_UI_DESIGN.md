# S48 design: Dakshitha's notes (design pass, 2026-11-04)

The notes themselves are in `S48_UI_NOTES.md`.

1. **Landing in one laptop screen.**
   - **Footer line:** "Your CV is encrypted and deletable."
   - **Measured:** the page is 860 px tall at 1280 wide.
   - **Cuts:** the owl art from 150 to 96 px, the landing gaps from 26 to 16 px, the h1 maximum from 56 to 48 px, and the promises row on one line. That saves about 130 px.
   - **Short screens:** under 740 px high, the owl is 72 px.
   - **Disclaimer:** the Grants.gov disclaimer stays word for word, as the API's terms ask.
   - **Walk check:** no vertical scroll at 1280×720 and 1366×768, on both tabs.
2. **Load sample on the signed-in student start.**
   - **Button:** a quiet "Load sample" beside "Your CV", with the hint "Fills the boxes with an invented student. Nothing is saved until you press Save."
   - **Text:** a shortened SYNTHETIC persona-ug in `web/sample_student.js`, with its canary line and no contact details.
   - **Marking:** a "SYNTHETIC example" tag, removed when the student edits the text.
   - **Existing text:** if a box already has text, an inline confirm reads "Replace what you typed with the sample?" with Replace and Keep mine.
   - **Stored CV:** the button is hidden when a CV is already stored. Guests keep "Try a sample student".
3. **Researcher CV on the first visit.**
   - **Card:** a visible card "Add your CV (optional)" above Build brief, with the hint "Used for cover-letter points and Scout. Stored encrypted. Contact details are blanked before a model reads it."
   - **Route:** it reuses POST /me/docs?audience=researcher. A saved document is ticked into the brief.
   - **Guests:** they see "Sign in to add your CV."
   - **Decided by Dakshitha:** optional.
4. **Change details and run again, both sides.**
   - **Where:** a "Change details and run again" button in the brief header and on each My Perch row, for signed-in users.
   - **What it does:** it opens the start screen prefilled from the brief's options and stored documents. Running again makes a new brief; the old one stays in My Perch with its saved leads.
   - **Researcher:** a "Choose someone else" link goes back to Find.
   - **Guests:** they keep "Start again".
5. **Cards.**
   - **Box grid:** `.box-grid { align-items: start }`. The empty documents text becomes "No stored documents yet."
   - **Lead card:** draw the agency tag only when it has text, and hide an empty `.tags`.
   - **Missing title:** the title falls back to "Untitled opportunity", never to the id.
   - **Spacing:** lead-card gaps are about 25% smaller. Closes and Award size share one row, and the model-text line is one line.
