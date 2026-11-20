# PulseReach — 3:00 product demo: shot-by-shot script, recording flow and edit timeline

The 00:00–00:40 intro is already rendered (`out/pulsereach_intro_40s.mp4`). §3 is the single working script.
Each row is one shot, with its timecode, what is on screen, the voiceover line (with its subtitle number in
`out/pulsereach_demo_subtitles.srt`) and the graphics/audio cue. The UI labels are taken from the current
frontend (`frontend/lib/i18n/messages/*.ts`). If the deployed build differs, follow what is on screen.

Rule for the whole video: only show what the app actually does on the deployed build. If a shot fails in
rehearsal, cut it and note it in the "Not captured" list (§7). Don't stage it.

---

## 1. Master timeline (3:00, 30 fps, 1920×1080)

| Time | Scene | Shots | Source | Lower third |
|---|---|---|---|---|
| 00:00–00:40 | Intro (0–20 s graded stock footage, 20–40 s constellation) | 1.1–1.4 | `out/pulsereach_intro_40s.mp4` (ends on an ivory frame) | — |
| 00:40–01:05 | 5 · Population intelligence | 5.1–5.5 | Recording **R1** (manager) | POPULATION HEALTH MANAGER |
| 01:05–01:30 | 6 · Care coordination | 6.1–6.5 | Recording **R2** (coordinator) | CARE COORDINATOR |
| 01:30–01:50 | 7 · Evidence-based completion | 7.1–7.4 | Recording **R3** (clinician) | CLINICIAN |
| 01:50–02:05 | 8.1 · Patient experience | 8.1.1–8.1.3 | Recording **R4** (patient) | PATIENT |
| 02:05–02:30 | 8.2 · Gemini assistant | 8.2.1–8.2.5 | Recording **R5** (patient) | PATIENT · *AI explanation, not a verified record* (that's the app's own badge; don't add a different one) |
| 02:30–02:50 | 8.3 · Patient engagement | 8.3.1–8.3.4 | Recordings **R6**, **R7** (coordinator reply insert), **R8** (patient) | PATIENT |
| 02:50–03:00 | Closing | 9.1 | Clean plate `out/pulsereach_intro_40s_clean_plate.mp4` 33.0–38.6 s + closing text (§5) | — |

Cut from the intro's ivory last frame (39.9 s) straight into shot 5.1. The app's light theme uses the same ivory
(`#f5f0e6`), so the cut feels like a dissolve.

---

## 2. Preparation before you record (do this in one rehearsal pass)

1. **Gemini is live on the deployed API.** `GET <api>/api/v1/ai/status` must show provider `gemini` with
   `availability` `configured_unverified` or `last_call_succeeded`. Without it, the portal shows *"Standard
   answer from your record"* and the copilot shows *"AI unavailable — standard summary shown"*. Those are honest
   fallbacks, but they are not Gemini, so don't record Scene 8.2 from them.
2. **Pick the patient.** Sign in as `patient.a`. The demo seed links this account to the first of the coordinator's
   20 assigned patients that has a date of birth and an open care gap. Write down the person ID shown in the
   portal *Health record*, then confirm the same person appears:
   - in the coordinator's *Assigned patients* list, with an open follow-up on *My worklist*;
   - in the clinician's *My patients* (the clinician has only the first 10 assignments). If the patient isn't
     there, the "same patient across roles" requirement can't be met for Scene 7. See §7.
3. **The patient needs ≥ 2 open care gaps.** Scene 7 closes one gap, and Scene 8 still needs an open recommendation
   to explain. With only one open gap, record R4/R5 *before* R3 and don't show the "updated status" in the portal.
4. **Find a valid evidence record for Scene 7.** *Document completion* only accepts an **Evidence record ID** that
   (a) belongs to this patient, (b) is a completed screening, well-child visit or referral, (c) matches the gap's
   rule and version, and (d) is not dated in the future (`backend/app/services/followup/completion.py`). Look in
   the profile's *Screening & History* and *Evidence Trace*. If no such record exists for the open gap, the
   backend will refuse (`evidence_not_found` / `evidence_rule_mismatch` …). That's correct behaviour, and it means
   Scene 7 can't be recorded with this patient. Don't fake it.
   - Possible genuine route, only if the gap concerns a referral: the clinician updates that referral to
     *Completed* (clinicians can update referrals), then documents completion with that referral ID. Check in
     rehearsal that the backend accepts it.
5. **Outreach must be allowed.** On the coordinator's follow-up, *Prepare draft* must produce *"Draft · awaiting
   human review"*. If it shows *"No draft — outreach is blocked."* (no consent or no permitted channel), pick
   another of the coordinator's follow-ups for Scene 6, or show the block as the safeguard it is.
6. **Clear leftovers from rehearsal.** Withdraw test requests in *My requests* (*Withdraw* → *Yes, withdraw*).
   Rehearsal outreach approvals and completions can't be undone, so rehearse on a different patient or
   environment where you can.
7. **Browser.** Chrome, a clean profile, the window exactly 1920×1080 (or record a 1920×1080 region), zoom 110%,
   light theme, no bookmarks bar, no extensions, macOS Focus/Do Not Disturb on. Type passwords off-camera, or sign
   in before you start recording and cut the typing. Never show the password field filled in. Keep the
   *synthetic data* banner visible. It's honest, and it shows these aren't real patients.
8. **Recorder.** OBS (canvas and output 1920×1080, 30 fps, CRF ≈ 16) or the macOS Screenshot toolbar (⇧⌘5,
   record selected portion). Record each role as a separate file. Move the cursor slowly and leave it still
   while the narrator talks.

---

## 3. Shot-by-shot script

Pace: about 140 words per minute, calm and unhurried. The voiceover text is identical to the subtitle file;
`#` is the subtitle cue number, and the time beside it is when the line starts. *Raw* is the matching clip
inside that shot's recording (offsets from the start of the R-file), so you know where to cut.

### Scene 1 · Intro (00:00–00:40) — already rendered

| Shot | Time | On screen | Voiceover (# · start) | Graphics / audio |
|---|---|---|---|---|
| 1.1 | 00:00.0–00:10.6 | Live action, teal/coral grade, slow push-ins and 0.7 s dissolves: aerial city at sunrise (0–3.9) → foggy morning commute on a bridge (3.2–6.2) → hospital facade (5.5–8.0) → clinician leading people down a clinic corridor (7.3–10.6) | **#1 · 00:00.6** Every day, people miss preventive care — **#2 · 00:04.6** not because care doesn't exist, **#3 · 00:07.2** but because the right people aren't always reached at the right time. | Music bed starts low |
| 1.2 | 00:10.6–00:20.6 | Live action: clinician reviewing imaging screens (9.9–12.9) → two nurses coordinating (12.2–15.2) → patients in a waiting area (14.5–17.5) → clinician at a laptop (16.8–20.6). From 18.4 s the footage darkens and constellation points emerge over it | **#4 · 00:10.8** Healthcare teams face fragmented information, **#5 · 00:14.0** disconnected follow-ups and limited visibility into who needs attention. | — |
| 1.3 | 00:20.6–00:30.5 | Connecting the information: points link into a dense network of teal edges | **#6 · 00:20.6** What if we could identify those gaps earlier, understand why they exist — **#7 · 00:24.6** and connect every person to the right care pathway? | Airy riser 00:28–00:34 |
| 1.4 | 00:30.5–00:40.0 | The network organises into concentric survey rings. Logo mark and **PULSE*REACH*** land at 34.1 s with *From insight to preventive action.*; ends on an ivory frame | **#8 · 00:33.9** Introducing PulseReach. **#9 · 00:35.9** Turning population-health insights into coordinated action **#10 · 00:37.7** and measurable preventive-care outcomes. | Music swell at 33.9; soft chime at 34.1 (logo) |

### Scene 5 · Population intelligence (00:40–01:05) — R1, `manager.a`

Lower third **POPULATION HEALTH MANAGER** from 00:40.0, held 3 s.

| Shot | Time | Raw (R1) | On screen / action | Voiceover (# · start) | Graphics / audio |
|---|---|---|---|---|---|
| 5.1 | 00:40.0–00:43.0 | 0–3 s | Sign-in screen with credentials already filled in off-camera → click *Sign in* → land on *Population overview* | **#11 · 00:41.5** PulseReach begins with population intelligence. | Hard cut from the intro's ivory frame; lower third in |
| 5.2 | 00:43.0–00:47.0 | 3–7 s | Slow pass over the headline indicators at the top. Don't hover each one | **#12 · 00:44.5** Healthcare teams gain visibility into preventive-care gaps, | — |
| 5.3 | 00:47.0–00:51.0 | 7–11 s | The **Population constellation**. Hover one programme so its tooltip shows *"{people} people · {open} open documented gaps"* | **#13 · 00:49.5** understand where attention is needed, | — |
| 5.4 | 00:51.0–00:57.0 | 11–17 s | Population insights: *Documented care gaps · "Where open gaps sit"* and *Evidence completeness · "Is screening history on record?"* | **#14 · 00:52.0** and explore geographic patterns through evidence-backed population insights. | — |
| 5.5 | 00:57.0–01:05.0 | 17–25 s | Scroll to **Geographic overview** (let the tiles load first). Click one area-level marker so its detail card opens with the aggregate figures. Hold. Only area-level aggregates appear here; suppressed small cells are fine to show. *Optional, if Gemini is live:* the copilot *Population briefing* | — (music) | Gentle 3–5% push-in on the held card |

### Scene 6 · Care coordination (01:05–01:30) — R2, `coordinator.a`

Lower third **CARE COORDINATOR** from 01:05.0, held 3 s.

| Shot | Time | Raw (R2) | On screen / action | Voiceover (# · start) | Graphics / audio |
|---|---|---|---|---|---|
| 6.1 | 01:05.0–01:09.0 | 0–4 s | *My worklist*: *My active follow-ups*, *New patient requests*, *Upcoming appointments* | **#15 · 01:06.0** Insights become action through coordinated care. | 12-frame cross-dissolve from 5.5; lower third in |
| 6.2 | 01:09.0–01:13.0 | 4–8 s | *Assigned patients* → open the chosen patient → profile sections *Care Gaps*, *Recommended Pathway* | **#16 · 01:09.5** Care coordinators can manage assigned patients, understand outstanding needs, | — |
| 6.3 | 01:13.0–01:18.0 | 8–13 s | The gap's explanation: the gap type description and *"Trace the evidence for this gap"* (*Evidence Trace* section) | **#17 · 01:15.5** prepare patient-friendly outreach and track follow-ups — | — |
| 6.4 | 01:18.0–01:22.0 | 13–17 s | Open the linked follow-up (*Care Coordination* → task page). Briefly show the tabs *Contact attempt · Status & assignment · Message patient · Escalate · Complete* | **#18 · 01:19.0** all within their authorised access. | — |
| 6.5 | 01:22.0–01:30.0 | 17–25 s | *Draft and review outreach* → *Prepare draft* → **"Draft · awaiting human review"** with the *AI-assisted wording* label and the disclaimer *"Simulated outreach only. PulseReach never sends SMS, e-mail…"*. Click **Approve (simulated, not sent)** and hold on *"Approved by you … Delivered: no — PulseReach does not send messages."* | **#19 · 01:22.5** Every message is reviewed and approved by a person; nothing is sent automatically. | Quiet UI tick on *Approve*; lift subtitles if the button sits in the bottom 15% |

### Scene 7 · Evidence-based completion (01:30–01:50) — R3, `clinician.a`

Lower third **CLINICIAN** from 01:30.0, held 3 s.

| Shot | Time | Raw (R3) | On screen / action | Voiceover (# · start) | Graphics / audio |
|---|---|---|---|---|---|
| 7.1 | 01:30.0–01:34.0 | 0–4 s | *My patients* → *Patients with open care gaps* → the same patient | **#20 · 01:31.0** Clinical decisions remain grounded in deterministic evaluation. | Cross-dissolve; lower third in |
| 7.2 | 01:34.0–01:39.0 | 4–9 s | *Care Gaps*: the open gap with its *Evidence* line, then *Evidence Trace* to show it comes from deterministic rule evaluation | **#21 · 01:35.5** Clinicians review the supporting evidence and document completed care, | — |
| 7.3 | 01:39.0–01:44.0 | 9–14 s | **Document completion** → paste the **Evidence record ID** (prepared in §2.4) → **Document completion and close**; hold through *"Checking evidence…"* | **#22 · 01:40.5** and PulseReach re-checks the rule before updating the patient's care status. | Quiet UI tick on *Document completion and close* |
| 7.4 | 01:44.0–01:50.0 | 14–20 s | The confirmed result: *"Completion documented on {gap} with evidence {evidence}. The engine re-checked the rule…"*, and the gap now shows **Closed — completed**. Use only the status the backend returns | **#23 · 01:46.2** AI never decides eligibility, and never marks care complete. | Hold; gentle push-in |

### Scene 8.1 · Patient experience (01:50–02:05) — R4, `patient.a`

Lower third **PATIENT** from 01:50.0, held 3 s.

| Shot | Time | Raw (R4) | On screen / action | Voiceover (# · start) | Graphics / audio |
|---|---|---|---|---|---|
| 8.1.1 | 01:50.0–01:54.0 | 0–4 s | *Your health overview*: tiles, *What to do next*, *Next appointment* | **#24 · 01:51.0** PulseReach also brings patients into the journey. | Cross-dissolve; soft music lift; lower third in |
| 8.1.2 | 01:54.0–01:59.5 | 4–9.5 s | *Recommended care*: open the remaining open recommendation and show its explanation. Keep *"Only your care team can mark care as complete."* readable | **#25 · 01:54.5** Each patient can understand their recommended care, review outstanding needs | — |
| 8.1.3 | 01:59.5–02:05.0 | 9.5–15 s | A quick glance at *Appointments* | **#26 · 02:00.0** and stay connected with their care team. | — |

### Scene 8.2 · Gemini assistant (02:05–02:30) — R5, `patient.a`

Record R5 2–3 times and keep the best *genuine* take. Never swap in another take's answer.

| Shot | Time | Raw (R5) | On screen / action | Voiceover (# · start) | Graphics / audio |
|---|---|---|---|---|---|
| 8.2.1 | 02:05.0–02:08.0 | 0–3 s | Back on the recommendation card: *Understand this recommendation* | **#27 · 02:06.0** With Gemini AI, patients can ask questions in natural language | Straight cut |
| 8.2.2 | 02:08.0–02:11.0 | 3–10 s, typing trimmed to ~1 s | Type or paste **"Why am I being recommended this preventive care, and what should I do next?"** (passes `guardrails.screen_question`; avoid *treatment, results, symptoms, diabetes, blood pressure*, which route to *"A clinician needs to answer this"* without calling Gemini) | **#28 · 02:10.5** and understand their care recommendations in simpler terms. | — |
| 8.2.3 | 02:11.0–02:15.0 | 10–25 s, wait trimmed | Click *Ask*, hold briefly on *"Preparing an answer"*, then the answer appears with the badge **"AI explanation, not a verified record"**. If it shows *"Standard answer from your record"*, it isn't Gemini: retake | — | Quiet UI tick on *Ask*; badge shown in the lower third (§1) |
| 8.2.4 | 02:15.0–02:19.5 | 25–32 s | *Optional:* switch the language to العربية, tap the preset topic *Why is this recommended?* and show the Arabic answer (RTL). If not captured, hold on the English answer instead | **#29 · 02:15.0** The assistant supports English and Arabic, | — |
| 8.2.5 | 02:19.5–02:30.0 | 32–45 s | Hold on the answer, with the badge and the escalation line readable | **#30 · 02:19.5** while keeping clinical decisions grounded in verified backend rules and human oversight. | Gentle push-in |

### Scene 8.3 · Patient engagement (02:30–02:50) — R6 → R7 → R8

| Shot | Time | Raw | On screen / action | Voiceover (# · start) | Graphics / audio |
|---|---|---|---|---|---|
| 8.3.1 | 02:30.0–02:35.0 | R6 0–15 s, trimmed | *Ask your care team* (or *My requests* → *Ask for help*) → type *"Could someone help me book this screening?"* → *Send*. Toast: *"Your request was sent to your care team."* | **#31 · 02:31.0** Patients can also request help, coordinate appointments | Cross-dissolve |
| 8.3.2 | 02:35.0–02:39.0 | R6 15–30 s, trimmed | *Appointments* → on an appointment, *Ask to reschedule* → *Send request* | **#32 · 02:35.5** and follow responses from their care team — | — |
| 8.3.3 | 02:39.0–02:42.0 | R7, 2–3 s | **Insert:** coordinator's *My worklist* → *New patient requests* → open the request → reply. Record the real reply action | **#33 · 02:40.0** bringing the entire preventive-care journey into one connected experience. *(continues into 8.3.4)* | Optional 2 s lower third **CARE COORDINATOR**; 6-frame dip to ivory in and out |
| 8.3.4 | 02:42.0–02:50.0 | R8 0–20 s, trimmed | Patient's *My requests* shows the request with **"Care team: {reply}"** and *Updated {date}*, then back to *Overview*. The note *"Your care team replies here in the portal. PulseReach does not send e-mail or SMS."* must not be contradicted by the voiceover | *(#33 ends 02:45.0)* | — |

### Scene 9 · Closing (02:50–03:00)

| Shot | Time | On screen | Voiceover (# · start) | Graphics / audio |
|---|---|---|---|---|
| 9.1 | 02:50.0–03:00.0 | Clean plate 33.0–38.6 s slowed to 10 s (or played and then held on the last frame). Centred: logo mark, **PULSE*REACH***, `IDENTIFY. COORDINATE. CONNECT. MEASURE.`, `From insight to preventive action.` Fade to midnight over the last 0.6 s | **#34 · 02:51.0** PulseReach. Better visibility. **#35 · 02:54.5** Better coordination. More connected preventive care. | Specs in §5; music resolves |

### Voiceover notes

- Lines #19 (01:22.5) and #23 (01:46.2) make the human-approval step and "Gemini doesn't decide care" explicit, as
  the brief asks. Both are true in the code: approval is *"Approve (simulated, not sent)"*, and completion is
  evidence-validated in the backend. Drop them if you want only the original wording (then also drop cues 19 and
  23 from the `.srt`).
- Shot 8.2.4: if the Arabic answer isn't shown on screen, keep line #29 anyway (the portal is fully localised and
  the assistant answers in the UI language). But it's stronger with the Arabic shot.
- Don't say "sent", "delivered", "texted" or "emailed" anywhere. The app only simulates outreach.

---

## 4. Recording plan (state-safe order)

Recording order isn't edit order. Each recording depends on the previous one's data. The *Shots* column tells
you where each file lands in §3.

| # | Role / account | Shots | What to capture | Raw length |
|---|---|---|---|---|
| R1 | Manager `manager.a@…` | 5.1–5.5 | Sign-in → overview → constellation → insights → map card | ~45 s |
| R2 | Coordinator `coordinator.a@…` | 6.1–6.5 | Worklist → patient → evidence → task tabs → draft + approve | ~50 s |
| R3 | Clinician `clinician.a@…` | 7.1–7.4 | Patient → gap evidence → document completion → closed status | ~40 s |
| R4 | Patient `patient.a@…` | 8.1.1–8.1.3 | Overview → recommendation explanation → appointments | ~30 s |
| R5 | Patient | 8.2.1–8.2.5 | Assistant question and answer (+ optional Arabic). 2–3 takes | ~45 s each |
| R6 | Patient | 8.3.1–8.3.2 | Help request + appointment change request | ~30 s |
| R7 | Coordinator | 8.3.3 | Reply to that patient request | ~15 s (2–3 s used) |
| R8 | Patient | 8.3.4 | *My requests* with the care-team reply → *Overview* | ~20 s |

If the patient has only one open gap (§2.3), record R4 and R5 before R3.

---

## 5. On-screen graphics

- **Lower thirds** (from the first frame of each role change, held 3 s, fading over 0.4 s): Geist (or Inter),
  22 px, letter-spacing 0.16 em, ivory `#f5f0e6` text on a midnight-teal `#0d4945` pill at 85% opacity, with a 3 px
  coral `#f0785b` bar at the start. Bottom-left, 64 px from the edges, so it never covers app content in the
  bottom-centre subtitle band.
  `POPULATION HEALTH MANAGER` · `CARE COORDINATOR` · `CLINICIAN` · `PATIENT`
- **Subtitles**: `out/pulsereach_demo_subtitles.srt` (full 3:00). Geist/Inter 34 px, ivory with a 60% midnight box,
  bottom-centre, 72 px above the bottom edge, at most 2 lines of about 45 characters each. Keep them off the app's
  primary action buttons. Lift the subtitles while a button you're clicking sits in the bottom 15% of the frame.
- **Closing (shot 9.1)**: background = clean plate `out/pulsereach_intro_40s_clean_plate.mp4` from 33.0 s to
  38.6 s, slowed to 10 s (or 33.0–38.6 then hold the last frame). Text, centred in the ring's empty space:
  - logo mark (`frontend/components/shell/logo.tsx`, or the frame at 36.5 s of the titled intro);
  - `PULSE`*`REACH`* in Fraunces 104 px (REACH italic, coral), kerning 16;
  - `IDENTIFY. COORDINATE. CONNECT. MEASURE.` in Geist 26 px, letter-spacing 0.3 em, mint `#a6dcd0`;
  - `From insight to preventive action.` in Geist 29 px, pearl;
  - fade to midnight over the last 0.6 s. No other claims.
- **Transitions between roles**: a 12-frame cross-dissolve, or a 6-frame dip to ivory. No wipes or zooms beyond
  a gentle 3–5% push-in on held frames.

## 6. Audio

- Music bed: ambient or neo-classical, around 70–80 BPM, with a swell at 00:33.9 (logo) and a soft lift at 01:50
  (patient). Duck it to about −22 LUFS under VO and keep the VO near −16 LUFS integrated. Total master −14 LUFS,
  true peak ≤ −1 dBTP.
- Sound design (subtle): low airy riser 00:28–00:34, soft chime at 34.1 s (logo), very quiet UI ticks on the key
  clicks (*Approve*, *Document completion and close*, *Ask*).

## 7. Not captured / must verify (fill in after rehearsal)

| Item | Shots | Status | Why |
|---|---|---|---|
| Live-action intro (city, hospital, staff) | 1.1–1.2 | Licensed Pexels stock footage, graded to the palette (`FOOTAGE_CREDITS.md`) | No video-generation model was available. Swap in generated shots later if you prefer |
| Gemini on the deployed API | 8.2.x | **Verify** (§2.1) | The local `prdeploy` stack has the LLM disabled; I couldn't check the deployed API |
| Same patient for clinician | 7.x | **Verify** (§2.2) | Clinician sees only the first 10 assignments |
| Valid evidence record for completion | 7.3–7.4 | **Verify** (§2.4) | The backend refuses completion without a qualifying completed record; the synthetic data may not have one |
| Outreach not blocked for that patient | 6.5 | **Verify** (§2.5) | Depends on consent and preferred channel |
| Arabic Gemini answer on screen | 8.2.4 | Optional | Needed only if you keep the Arabic claim on screen |

## 8. Final checks before export

Duration exactly 03:00.000 · every UI shot from the deployed app · Gemini answer carries the *AI explanation*
badge · no credentials, tokens or dev tools visible · same synthetic patient throughout (or note the exception) ·
VO lines match the visible action · intro and closing branding match · loudness as in §6 · 1080p export
(H.264 High, 16–20 Mbps, AAC 320 kbps, 48 kHz).
