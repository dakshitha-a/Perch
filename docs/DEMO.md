# Demo Day run sheet

[Back to the README](../README.md) · [Deploying](deploy.md)

This is the run sheet for the five-minute demo on Friday 6 November 2026. The click path comes from the product review in [S51_PRODUCT_REVIEW.md](design/S51_PRODUCT_REVIEW.md). Nothing here holds a host name or a password. The deploy's address is in the operator's private notes.

## Before the demo

Do these on the morning of the demo, in this order.

- **Check the spend ledger.** The deploy's own ledger should have at least 5 USD left under its cap.
- **Clear the guest limits.** Source the deploy's env file, then run `scripts/demo_reset.py` once to count and once with `--apply` to delete. It clears the guest rate windows and the guest model budgets for today in the deploy's Redis. It does not touch sessions, signed-in budgets or the spend ledger.
- **Test from a phone on the venue network.** Open the deploy's address on the venue Wi-Fi and again on mobile data. The app is on port 443 and sign-in is on port 10000. Some venue networks allow only port 443, so the sign-in page may not load there; see the port section below.
- **Sign in once as `demo-presenter`.** This is a SYNTHETIC account. Accept the consent, and set the role. The password is in the operator's private env file, never in this repository.
- **Pre-build the researcher brief on that account.** Wait for Ready. Keep two individual-lab leads and draft the hand-off. Ask one Scout question so the thread already holds an answer.
- **Pre-build the student brief on that account.** Use Try a sample student. Open the Samples tab and find where the card that fails on GPA sits.
- **Keep two windows.** One is signed in on My Perch. One is a private window, signed out, which shows what the audience sees.
- **Load the films.** The presentation shows three films: the researcher side, the student side, and Scout on the student side. Check that each plays from the slides.
- **Stay signed in.** A session ends after 30 idle minutes, so use the app at least every 25 minutes.

## Audience sign-in

- **Account:** the audience signs in as `demo`, password `demo`. It is one SYNTHETIC account that everyone shares.
- **What they see:** a notice on every screen, and again beside the CV boxes: "Shared demo account. Everyone who signs in sees what you save here. Do not paste a real CV." They land straight in the app, with no Welcome step.
- **Cleared nightly:** a timer wipes the account's CV, entries, documents, briefs, kept leads, hand-offs, cover points and Scout sessions at 03:30 local time. The account, its consent and its roles stay. Its spend record stays too, so the wipe does not reset the budget. Run the wipe by hand before the demo if the account has been used.
- **Lockout:** after 10 failed sign-in tries the sign-in service locks the account. It unlocks by itself after 1 to 15 minutes. Presenters should not type the password wrong in front of the audience.
- **Presenter account:** `demo-presenter` stays separate and unshared, so the pre-built briefs on it are not wiped.
- **Operator setup:** the steps are in the comments of `.env.example` (PERCH_SHARED_ACCOUNTS) and `deploy/systemd/v1/perch-demo-wipe.service`.

## Who is on the projector

A live researcher brief shows a real researcher's name, and its hand-off is written in the first person in that name. Question 51 in `bridge/QUESTIONS.md` asks Dakshitha to decide. The default is the aliased example brief, with the researcher shown as PI-4. Do not search a stranger's name live.

## The click path

Five minutes. The presenter has a laptop on the projector and the audience has phones.

| Time | Step | What to click | Expected screen | Fallback |
|---|---|---|---|---|
| 0:00 | Landing | In the private window, show the tagline. Say: scan the code, tap Student, then Try a sample student. | The landing page with a Try a sample student button, since accounts are closed. | Say Try it as a guest, the small link under the buttons. |
| 0:30 | Researcher brief | In the signed-in window, open the pre-built researcher brief from My Perch. | Ready, the Grants tab, Match pills, and the centre-grant line in its own fold. | Open `/example.html`. |
| 1:00 | One card | Open Why it fits on the top individual-lab lead, then press Evidence. Point out that the date and amount are copied from the record. | Cited text and the evidence panel on the right. | The same card in the example. |
| 1:40 | Temple internal and Industry | One tap on each tab. Check the Temple tab in the morning and skip it if a closed call shows. Read the line on an industry card: inferred from public signals, not verified. | Two short lists. | Skip and say the example has them. |
| 2:10 | Ask Scout | Show the answer asked in the morning. Then press the Deadlines chip, which code answers at once. Do not type a new open question. | Cited dates in seconds. | `/example.html?tab=scout`. |
| 2:50 | Compare and hand-off | Open Compare with the two kept leads. Scroll to the hand-off drafted in the morning. Point to the Model text label, the ERA line and the words that Perch never sends it. Do not press Open in my mail app. | The comparison table and the hand-off draft. | `/example.html?tab=compare`. |
| 3:40 | Student | Open the pre-built sample-student brief. Show the Sample data badge, a card with check marks and question marks, and on the Samples tab the card that fails on GPA. Show cover points only if the morning run came back with no flags. | A SYNTHETIC student brief with rule lines. | `/example.html?side=student`. |
| 4:30 | Close | Say: every claim cites a public record, nothing is sent, and the audience is using it now. Put the QR code back up. | The QR code slide. | None. |

## If something fails

- **Sign-in fails:** do steps 2 to 7 on the example pages. They need no sign-in and call no model.
- **The deploy is down:** show the three films and the example pages. The fallback build is offline since 5 Nov (S54); it stays at the tag `v0.1-demo-fallback` as history.
- **Guests see empty reasons:** the guest budget is used. The lists, dates and rules still work. Say so and move on.
- **Slow steps to avoid live:** a fresh researcher brief takes about 38 to 50 seconds. Cover points can take up to two minutes. An open Scout question and Run again are also slow.

## The ports

Only Dakshitha changes these. They change what the public address serves.

Since 5 Nov (S54), port 443 serves v1 and port 8443 is closed. The fallback build is offline. The deploy's env file sets `PERCH_PUBLIC_URL` to the address with no port. To check what the tunnel serves:

```sh
tailscale funnel status
```

- **Guests are fine:** a guest needs no sign-in, so a guest session works on 443 alone.
- **Sign-in returns to 443:** the sign-in client accepts the return address on port 443 (added in S52), and the app sends people back there.
- **Sign-in uses port 10000:** the sign-in page itself is served on port 10000. If the venue blocks that port too, sign in as `demo-presenter` on mobile data, or before you arrive, and keep the tab open. An idle session ends after 30 minutes, so sign in shortly before you present.
- **Check it:** sign in once on the public address and open a brief before the demo starts.
- **The presenter can use a hotspot:** only the presenter needs the sign-in port, which is 10000.
- **Never remove the Keycloak container:** do not run `docker rm` on it. Its users live inside it.
- **Question 52** in `bridge/QUESTIONS.md` records why v1 moved to 443; it is closed.
