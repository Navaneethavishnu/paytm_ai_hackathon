# Handoff prompt: paste this into a new Claude Code session in this folder

I'm Navaneethamahavishnu, a solo builder: **Team Absolute AI**. Our project is **Merchant Success AI**. It's for the Paytm Build for India AI Hackathon, Track 3 "Autonomous AI Teammates". **The finale is today, 15 November 2026, in Chennai.** Help me finish preparing.

`CLAUDE.md` loads automatically and holds the full build history, rules and architecture. Don't re-derive what's in it. Below is everything that happened after it was last updated.

## Ground rules (still apply)
- **Do NOT commit or create git commits** unless I ask. This folder is not a git repo.
- The Sarvam API key lives only in `.env` (gitignored). Never put it in `.env.example` or any other file.
- Ask me before adding any Python or npm dependency.
- Working demo > reliability > polish > new features. Today is the finale, so avoid risky changes to the agent, policy or demo cache.
- After any code change, run `.venv/bin/python -m pytest -q`. The expected result is **184 passed, 1 skipped** (the skipped one is a live Sarvam test).

## Current state: everything is built and verified
- Steps 1–7 and Case 4 (proactive double payment, the customer chooses keep or refund) are done.
- Checks:
  - 184 tests pass.
  - `scripts/stress.py`: 150/150 cached live runs (15 scenarios × 10).
  - 300/300 chaos runs at 25% tool failure, with no double payout or refund.
- 15 demo situations: 8 fully automatic, 3 after a human approves, 3 escalated, 1 asks for details. Plus 6 extra merchants (M1007–M1012, `app/seed_bulk.py`) with 115 more payments (130 total) hiding 13 more scenarios incl. R-08, R-23, G-06.
- UI (15 Nov): timeline tabs Graph (default, 17-node LangGraph view) | Cards | Ops approvals | History; the right Ops column was removed. `GET /cases` (Ops token) lists case history. Deck has 17 slides (new slide `audit`).
- Policy limits:
  - Refunds: auto ≤ ₹5,000 (R-21); Ops approval ≤ ₹1,00,000 (R-22); otherwise escalate (R-23).
  - Payout retries: auto ≤ ₹50,000 (R-07); above that, Ops (R-10); a second retry needs Ops (R-08).
- Speed: live Sarvam takes 9–17 s per case; the demo cache about 0.03 s; replies about 0.2 s.

## How to run the demo
```
# Terminal 1 (backend), from the project root
.venv/bin/uvicorn app.api:app --host 0.0.0.0 --port 8000
# Terminal 2 (web app)
cd web && npm run dev        # http://localhost:5173
```
- `.env` already has `DEMO_MODE=true`, so typed prompts replay from `demo_assets/llm_cache.json`. Voice needs internet.
- **`OPS_TOKEN` is NOT set in `.env`.** It falls back to `demo-ops-token`. Remind me to set my own and enter it in the Ops panel's "token" field.
- **Servers may still be running from the old session** on ports 8000 and 5173. That backend used a scratch database in the old session's temp folder. Check with `lsof -i :8000 -i :5173`, then stop those processes before starting fresh with the project's own database.
- Reset the demo with the top-bar **↺ Reset**, or `POST /api/demo/reset` with the `X-Ops-Token` header.

## The slide deck (made 15 Nov)
- **Online deck:** https://claude.ai/artifact/EhD2xrjqdU44XbMuzT7UER
  - Present it there; Export → .pptx or PDF.
  - It's private until I share it.
  - To edit it, read it with the Artifact tool first, then publish only the changed `project/...` files to the same url.
- **Local copies** in `presentation/`:
  - `Merchant-Success-AI.pdf`: 16 pages at 1920×1080, the offline backup.
  - `Merchant-Success-AI.html`: all slides in one page; needs internet only for fonts.
  - `images/`: the two app screenshots.
  - `source/project/`: `deck.json`, `deck.css`, `slides/*.html`.
  - The local copies hide the small icons (only the online deck draws them).
  - The PDF was made with headless Chrome `--print-to-pdf` from the HTML file. It has a print rule that turns off animations and zoom.
- **Look:** light theme, Space Grotesk and Inter fonts.
  - Colours: blue `#0A5FC2` = automatic or policy, amber `#9E4E00` = Ops approval, red `#B01F2C` = escalate, violet `#6A3DC0` = AI, teal `#0B6E61` = verify.
- **Team Absolute AI and my name** appear on the cover and the thank-you slide. Every content slide's footer reads "Team Absolute AI · page number", set in `deck.css` by `.pg::after`.
- **Slide order:**
  1. cover
  2. problem
  3. 8 steps
  4. principle ("AI proposes. Policy decides. Verifier confirms.")
  5. architecture
  6. LangGraph state machine
  7. policy table
  8. four demo cases
  9. live app screenshots
  10. Case 4 flow
  11. nine guardrails
  12. reply pipeline (placeholders → code fills values → validator)
  13. Tamil voice with Sarvam
  14. proof numbers
  15. path to production
  16. thank you

## Demo script
`DEMO_SCRIPT.md` has five parts:
- a 10-minute pre-stage checklist;
- a 3-minute live demo: Case 1 Tamil R-07 → Case 2 ₹12,000 R-22 approve → Case 3 G-01 → Case 4 ⚡ Double payment → close;
- a troubleshooting table;
- Q&A with 15 questions;
- the numbers to remember.

**It's outdated in two ways:** it doesn't introduce Team Absolute AI or my name, and it was written before the slides. So it doesn't say when to show slides and when to switch to the live app.

## Pending: offered, not yet done (ask me which to do)
1. **Update `DEMO_SCRIPT.md` to match the slides:**
   - intro with my team and name on slides 1–4;
   - switch to the live app for the four cases;
   - back to slides 11–16 for guardrails, proof and close;
   - with timings.
2. **Optional UI polish:**
   - demo prompt chips get cut off and should wrap;
   - the Ops evidence table is too wide (the "Customer" column is cut off);
   - check the layout at 1280×720 and 1366×768.
3. **Optional small eval** (proposed, not built):
   - about 40 labelled merchant messages (English, Tamil, Tanglish, typos, injection attempts), run live with the cache off;
   - report understanding accuracy, end-to-end accuracy, safety (must be 100%) and latency;
   - compare against a no-AI regex baseline.
   - It must not touch the demo cache.
4. **My own to-dos:** set `OPS_TOKEN`, rehearse 2–3 times with a timer, record a backup video, copy the PDF to a USB stick or my phone.

Start by telling me in a few lines what you understood, then ask which pending item to do first.
