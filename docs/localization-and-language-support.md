# PulseReach — English and Arabic Support

Supported locales: `en` (default, left-to-right) and `ar` (right-to-left). The two-letter codes are
the only representation in API contracts (`preferred_language`, `locale`, `language`, `?lang=`).

Code: `backend/app/core/i18n.py` (catalog, negotiation, formatting, `AppError`),
`backend/app/core/errors.py` (localized error envelope), portal/engagement routers,
`backend/app/services/outreach/*` and `backend/app/services/ai/guardrails.py` (Arabic outreach).

## 1. Locale resolution

1. `?lang=en|ar` query parameter (explicit override for one request);
2. the authenticated user's `preferred_language`;
3. `Accept-Language` (quality values honoured; region subtags such as `ar-AE` map to `ar`);
4. `DEFAULT_LOCALE` (`en`).

Unsupported values fall back to the next step. Registration stores the language from the body,
otherwise from `Accept-Language`. `GET/PATCH /api/v1/me/preferences` reads/changes it (`422` for
anything other than `en`/`ar`); `PATCH /api/v1/me` also accepts `preferred_language`.

## 2. What is localized

| Area | How |
|---|---|
| Error messages | `detail` stays the stable English text (existing clients); `error.message` is localized and `error.message_key` / `error.locale` are added for catalog-backed errors (auth, authorization, workflow, linking). `401`/`403`/`429` without a key are localized from the status. Validation errors keep `detail` and localize `error.message`. `Content-Language` header on errors. |
| Auth / profile messages | `MessageOut {message, message_key, locale, direction}` |
| Portal responses | `locale`, `direction` + localized labels, titles, descriptions, explanations, dates |
| Follow-up content | Task templates (`message_key`) rendered in the requested locale for patients and in the task language for staff |
| Care recommendations | Gap-type titles/descriptions, programme names, documented next steps, evidence lines |
| Appointment / referral / request / task statuses | `status_label`, `*_type_label` |
| Outreach drafts | Arabic deterministic template + Arabic guardrails (below) |

Not translated: database identifiers, clinical codes, rule ids, enum values, API field names,
free text written by people (patient messages, staff messages are returned as written).

## 3. Arabic specifics

- UTF-8 end to end (PostgreSQL `TEXT`, JSON responses without escaping requirements); covered by
  round-trip tests with Arabic names and messages.
- Right-to-left metadata: `direction: "rtl"` on every localized response.
- Messages are complete sentences per locale with named placeholders — no concatenation of
  translated fragments. Interpolated values in Arabic (ids, dates, numbers, Latin names) are
  wrapped in Unicode first-strong isolates (U+2068 … U+2069) so they cannot reorder the sentence.
- Dates: `day month-name year` with Arabic Gregorian month names (`16 نوفمبر 2026`) and Western
  digits, as used in UAE government Arabic content; ISO values are always present alongside.
- A test enforces that every catalog key has both locales with identical placeholders.

## 4. Clinical determinism

Language never reaches the evaluation engine. Tests assert identical evaluation results, ad-hoc
evaluations and dashboard aggregates for `en`, `ar`, `Accept-Language: ar` and after changing the
user's preference.

## 5. AI and outreach in Arabic

- Outreach previews and drafts now support `ar` (previously blocked with `template_unavailable` /
  `language_unsupported`). Other languages are still refused, never silently answered in English.
- Same gate as English (consent, authority, open gap, channel, next step) before any model call.
- Deterministic Arabic draft built from approved Arabic facts (programme, gap category, next step).
- Model output in Arabic is validated by the shared checks (length, identifiers, links, invented
  numbers — Eastern Arabic digits are normalized first) plus Arabic lexicons for clinical claims,
  risk/probability, overdue/due/completed/eligibility claims, coercion/urgency, fear, and invented
  logistics (appointments, facilities, costs, dates, weekdays, months); it must contain
  `مختص` (licensed healthcare professional) and contain no Latin words except `IFHAS`. Any
  violation falls back to the deterministic Arabic draft and is recorded in the AI audit.
- Prompt `outreach-v3` adds per-language rules (`OUTREACH_LANGUAGE_RULES`).
- Human review is identical: only `outreach.review` holders approve; approval re-validates the
  (possibly edited) Arabic text and records `simulated_not_sent`.
- Staff explanations (`POST /explanations`) remain English; patient explanations are deterministic
  localized templates (no model).

Limitation: the Arabic lexicons are substring-based and conservative; they have not been reviewed
by a clinical Arabic language specialist. Treat Arabic content as requiring the same human review.
