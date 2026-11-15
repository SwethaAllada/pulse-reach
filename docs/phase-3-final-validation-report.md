# PulseReach — Phase 3 Final Design Validation Report

| | |
|---|---|
| **Step** | Phase 3, Step 5 — final design validation audit |
| **Date** | 2026-11-15 |
| **Repository state audited** | `main` @ `850d5c0` ("Documentation update"), working tree clean at start |
| **Canonical design audited** | `docs/phase-3-database-design.md`, revision 2.5 (1,630 lines, status DRAFT) |
| **Nature** | Documentation and validation only. Nothing was implemented, and no audited file was modified. |
| **Evidence labels** | **VERIFIED** = checked against a file or by a command in this audit. **ASSERTED** = stated by a project document with no independent evidence in the repository. **UNVERIFIED** = could not be checked. |

---

## 1. Executive summary

**Verdict: READY WITH CONDITIONS** (section 12). It is not READY and not NOT READY.

The design is largely coherent. Inventory, relationships and the main safeguards are sound. Several things hold up under checking:

- The documented inventory matches in every document that states it: 9 official, 12 clinical and 18 synthetic tables (39 in total), plus the conditional `official.working_calendar`.
- All 215 raw-file checksums verify.
- The YAML, the loader, the mapping and the design agree on every count: 54 rules, 249 items, 23 open questions, 7 review-flagged rules and 9 unresolved items.
- The 80 loader tests pass.
- The synthetic-versus-real markers are enforced by CHECK constraints on all 18 synthetic tables.
- D18 states no legal sufficiency.
- Both ERDs have no syntax defect that structural and manual review could find.

Nothing in the audited set, however, supports a plain READY. The reasons:

1. **The first migration is gated by two unconfirmed technical decisions.** D6 (plain coordinates versus PostGIS) and D7 (Alembic with SQLAlchemy 2.x) are "recommended, awaiting owner confirmation". Three constraint names (CD-1, CD-7, CD-10) also still await owner confirmation (F-001, F-002).
2. **The documents disagree on what D2 blocks.** The design says D2 does not block the schema skeleton. The loading strategy says no synthetic table may be built until D2 is clinically approved. Phase 4 cannot tell whether the 18 synthetic tables may be migrated (F-003).
3. **The database does not enforce the central clinical safeguard.** Nothing in the DDL design stops a decisive result being stored against one of the 7 non-authoritative rules. The existing loader also treats a null, empty or missing `requires_clinical_review` as "authoritative". The loader's item authority ignores the parent rule. `v_item_outstanding` ignores parent authority too, and `rule.requires_clinical_review` defaults to `false` (F-004 to F-008).
4. **Several design decisions are still required before DDL is written.** Examples: facility unique keys that allow only one register vintage, a current-observation view ordered by a column that is NULL for all 157 SCAD files, a current-evaluation view that returns stale rows, and a completion marker that accepts partial screenings (F-009 to F-012).
5. **D13 blocks synthetic data generation in practice.** No facility profile can exist until a licence status is confirmed. Every screening, visit and appointment row needs a profile (F-013).
6. **Owner approvals are asserted, not evidenced.** No approver, date or record exists in the repository for D1, D8, D16, D18 or CD-3 to CD-11. This audit treats them as ASSERTED (F-014).
7. **Several documents still carry corrections that were withdrawn.** Examples: the manifest's "disclosure rounding", the acquisition report's "sum exactly", and the loading strategy's "consumer must AND".

**Finding totals:** 2 Critical (gating), 13 High, 30 Medium, 13 Low or Info (some Low IDs consolidate many minor items). Details are in section 11.

**What this audit did not do.** It did not recompute any source data, including the 42, 479 and +10,940 figures. It did not render the ERDs, because no local Mermaid renderer exists. It did not run PostgreSQL, SQLAlchemy or Alembic.

---

## 2. Audit scope and files inspected

All 14 required documents were read in full, apart from the YAML and loader inspection described below. Five read-only reviewers divided the work (official schema, clinical and synthetic schema, source data, YAML and loader, decision register and ERDs). Spot-checks of key claims were made against the repository afterwards.

| # | File | Inspection |
|---|---|---|
| 1 | `docs/phase-3-database-design.md` | Full (all chunks) |
| 2 | `docs/erd/official-schema-erd.md` | Full |
| 3 | `docs/erd/clinical-schema-erd.md` | Full |
| 4 | `docs/mappings/official-source-to-table-mapping.md` | Full |
| 5 | `docs/mappings/clinical-yaml-to-database-mapping.md` | Full |
| 6 | `docs/mappings/data-loading-and-validation-strategy.md` | Full |
| 7 | `docs/mappings/phase-3-reconciliation-report.md` | Full |
| 8 | `docs/data-acquisition-report.md` | Full |
| 9 | `data/metadata/data_quality_report.md` | Full |
| 10 | `data/metadata/data_dictionary.md` | Full |
| 11 | `data/metadata/synthetic_data_spec.md` | Full |
| 12 | `data/reference/source_manifest.yaml` | Full |
| 13 | `data/README.md` | Full |
| 14 | `docs/clinical-rules.md` | Full |
| — | `docs/phase-3-database-design-review.md` | Context only (earlier review, not a source of truth) |
| — | `data-pipeline/rule_loader/*.py`, `data-pipeline/tests/*.py`, `pytest.ini`, `requirements.txt` | Full |
| — | `data-pipeline/rules/**/*.yaml` (5 files) | Parsed in full by script; not read line by line |
| — | `data-pipeline/ingestion/`, `transformation/build_facilities.py` | Inventory only. `validation/` holds only `.gitkeep`, so no validation code exists |

**Citation convention.** Line numbers refer to the repository at `850d5c0`. "Design" means `docs/phase-3-database-design.md`. "Strategy" means `data-loading-and-validation-strategy.md`.

---

## 3. Schema and table inventory verification

### 3.1 Result

| Schema | Documented count | Found | Consistent across documents? |
|---|---|---|---|
| `official` | 9 (+1 conditional) | 9 + `working_calendar` | **Yes.** Design L64, ERD entities, mapping §§2–10 |
| `clinical` | 12 | 12 | **Yes.** Design L65, clinical ERD, strategy L60–69 |
| `synthetic` | 18 | 18 | **Yes** in the design (L66, §5.6A registry). **No** in the synthetic spec, which still says 11 (F-040) |
| Total | 39 + 1 conditional | 39 + 1 | 9 + 12 + 18 = 39 |

No table is missing, duplicated or renamed across the design, ERDs and mappings. Entity counts were checked by a structural script: 9 entities in the official ERD and 12 in the clinical ERD, with none duplicated, undefined or unreferenced. There is no synthetic ERD (F-023).

### 3.2 `official.working_calendar` (conditional on D12)

- It is excluded from the ERD (official ERD L7, §8.6) and not created by the mapping (OU-9).
- The design (L423–424, D12 L1342) defines it conditionally.
- D12 is open. The table would break the design's own provenance rule (P1), because `source` is free text, and no calendar source exists in `data/raw/`. The table count therefore depends on D12 (F-036).
- D12 also gates the `IFHAS-WF-REFERRAL-15WD` deadline and `slot_type = 'weekend'`.

### 3.3 View inventory

The design's view list (L70) omits `clinical.v_rule_item_effective_authority`, which is defined at L587 and listed in the clinical ERD (L7). See F-041.

---

## 4. Column, relationship and constraint consistency

### 4.1 The four `indicator` metadata columns

Confirmed as an ERD omission. The design (L274) defines `statistical_population`, `geographic_coverage`, `calculation_method` and `data_sources_text` as TEXT NULL. The official ERD `indicator` entity (L88–101) has none of them. The mapping records the omission (D-4, L489). The ERD's own discrepancy list (§9) does not, and ERD L318 says "none of the nine tables was omitted" (F-024).

### 4.2 Relationships and integrity

| Area | Assessment |
|---|---|
| Foreign keys and delete behaviour | RESTRICT on delete and update everywhere, with no CASCADE (design L128). The ERDs show only the delete rule. Reloading official facilities is blocked while synthetic profiles exist (F-026). A run-purge job contradicts the append-only triggers (F-021) |
| Parent-child rule and item authority | Composite FKs on the full version key. `v_rule_item_effective_authority` is correct as described, but it is not used by `v_item_outstanding` (F-007), the loader (F-005) or the strategy document (F-041). Its join type is UNVERIFIED because no SQL exists |
| Rule-load and evaluation-run provenance | `rule_bundle_load_id` FKs exist. Which rules belong to each load is not stored, so an evaluation cannot be checked against its run's rules (F-016). `evaluation_run` has no completion marker (F-010) |
| Patient, guardian, consent, screening | Same-run and same-patient composite FKs are systematic. Child-ness, consent precedence and consent currency are trigger or test only (F-018) |
| Evaluation reason and care gap | Same-run, same-patient and same-rule composite FK. The "gap-yielding" status set is undefined (F-019) |
| Appointment, referral, outreach, completion | Composite FKs include `profile_id`. Completion evidence is under-constrained (F-012) |
| Append-only history and current state | Evaluation rows are append-only. `v_eligibility_current` selects the latest row per rule and can show stale results (F-009). Care gaps, referrals and appointments are mutable, contradicting principle P4 (F-020) |

### 4.3 Rules that cannot be enforced by ordinary FK or CHECK

For each rule the table gives the reason and the mechanism the design needs.

| Rule | Why a plain FK or CHECK cannot do it | Mechanism needed |
|---|---|---|
| Evaluation rule belongs to its run's rule bundle | No membership table exists to reference | New membership table plus FK or trigger (F-016) |
| Non-authoritative rule yields no decisive status | Needs a status-dependent FK | Marker-FK pattern from design §2.5 is feasible (F-004) |
| Closing evidence dated on or after gap identification | Cross-row temporal comparison | Trigger (F-012) |
| Consent covers the gap's rule, and is current at send or score time | Temporal and scope logic across tables | Trigger (design §6.3 #7) |
| Child outreach goes to the guardian; a child's consent comes from a guardian | Depends on age at the reference date | Trigger or test (F-018) |
| Facility profile only for a usable (operating) facility | A view cannot be an FK target | Trigger against `v_facility_usable` |
| Reported `reason_code` is among the fired reasons | Cross-row set membership | Trigger or test |
| `row_role` equals "any member is an aggregate" | Derived across ten FK columns | Loader test or a view (F-031) |
| `no_documented_screening` requires history `available` as of the reference date | Temporal | Trigger |
| Facility never joins to SCAD observations (R-O4) | A negative join rule | `pg_depend` test for views; code review for joins (F-037) |
| Official ✗ synthetic FK direction, official ↔ clinical | Schema-boundary rule | `pg_constraint` / `pg_depend` test (design §6.3 #12) |
| Overlapping consent precedence | Not yet defined | View definition plus trigger (F-018) |

**Checks the design calls "trigger" or "test" but that plain composite FKs could express** (design L1130 says triggers only where no FK can express): consent scope pathway equals the rule pathway; event rule type for IFHAS screening and Well-Child visit; assessment instrument equals the rule instrument; appointment type matches the event; guard-to-reason pairing. See F-022. The "exclusion rules cannot be machine-evaluable" rule is intra-row, so a one-line CHECK would do (F-034).

### 4.4 Cross-document column discrepancies (recorded, not resolved)

| Ref | Discrepancy |
|---|---|
| F-024 | Official ERD omits the four `indicator` metadata columns |
| F-025 | The `source_file` column table in the design is split by an inserted table, so four columns render as orphan rows |
| F-029 | Design describes `source.contains_data` and `source.fit_for_use` at source level; the mapping sets them only at file level |
| F-030 | Design says 215 files are registered; the mapping registers 214 |
| F-032 | `facility`: `null_geometry` can be emitted by the transform; the design's `geo_quality` vocabulary has four values and nullable `source_*` coordinates that cannot load as NULL |
| F-033 | Raw and usable coordinates are not tied by CHECKs for `ok` and `swapped_repaired` |
| F-035 | `has_insurance` collapses `''` and unidentified into NULL, undocumented in the design |
| F-042 | Guard `result_status` / `reason_code` nullability: mapping says NOT NULL; the design and clinical ERD say "not stated" |

---

## 5. ERD validation and rendering

### 5.1 Rendering

**Rendering was NOT performed.** No local renderer exists: `which mmdc` found nothing, `npx --no-install mmdc -V` failed, `node_modules/.bin` is absent, and the Python `mermaid` package is not importable. Nothing was installed, and no network was used. No claim of successful rendering is made.

### 5.2 Syntax review (structural script plus manual grammar review)

| Check | Official ERD | Clinical ERD |
|---|---|---|
| Mermaid blocks | 2 (`erDiagram`, `flowchart`) | 2 (`erDiagram`, `flowchart`) |
| Entities | 9 | 12 |
| Relationships | 19 | 14 |
| Cardinality tokens | all valid | all valid |
| Duplicate entities, unclosed blocks | none | none |
| Entities referenced but undefined | none | none |
| Reserved-word conflicts | none found | none found |
| Flowchart bracket, quote and `subgraph`/`end` balance | balanced | balanced |

**Verdict:** no syntax defect found. This is a static-review result and not proof of rendering. Two points need a real renderer to confirm (UNVERIFIED): multi-key attribute markers such as `PK, FK` need Mermaid v10 or later, and quoted flowchart edge text containing `;` and `→`.

### 5.3 Content findings

- The official ERD still says reconciliation means "leaves sum to aggregate", a premise the design withdrew (F-024).
- The clinical ERD labels every rule-question link "blocks" or "blocked by". The CD-2 decision, which would give links blocking semantics, has not been approved (F-039).
- One clinical flowchart edge points the `reason_code` FK at `evaluation_status` rather than `reason_code`. The `component_result` → `rule_item` and `evaluation_reason` → `reason_code` inbound FKs are omitted (F-039).
- CHECKs and generated columns appear only as comments, which both ERDs acknowledge. Not even noted: the `unresolved ⇒ requires_clinical_review` CHECK, the `rule_condition` evaluability CHECK, the `observation` value-marker CHECK.
- **No synthetic ERD exists.** The most constraint-dense part of the design (same-run and same-patient composite FKs, evidence-marker FKs) has no diagram to review before Phase 4 (F-023).
- The official ERD shows only the delete rule; the design also requires `ON UPDATE RESTRICT` (F-038).

---

## 6. Clinical safeguards assessment

Enforcement is classed as **DB** (a constraint or privilege), **Loader**, **Engine** or **Doc** (written only).

| # | Safeguard | Where enforced | Assessment |
|---|---|---|---|
| 1 | Elevated health risk, programme eligibility, preventive-care eligibility, documented care gap and operational priority are distinct | Partly DB | The AI score sits in separate columns with separate grants, and a gap carries an FK to its evaluation. Programme and preventive eligibility share the same `eligible` status and differ only by `rule.rule_type`. "Elevated health risk" is not modelled, and no document says `priority_score` is not a health-risk measure. The gap-yielding rule types and statuses are undefined (F-019) |
| 2 | Missing screening history is not proof of no screening | DB plus trigger | `history_availability` exists and `not_screened` was renamed `no_documented_screening`. The trigger needs availability as of the reference date. No row for a patient and pathway has no stated meaning, and the table works at pathway level only (F-019) |
| 3 | Unknown is not converted to false | DB | Nullable booleans with `IS TRUE` evidence. Gaps: `rule.requires_clinical_review DEFAULT false` (F-006), the loader's `bool()` (F-005), and two representations of unknown for nationality |
| 4 | Unresolved rules cannot produce authoritative results | Generated `is_authoritative` and CHECK. **Statuses on evaluations are Engine only** | **Gap (High):** F-004 |
| 5 | Parent-aware rule-item authority | View only | Correct in the design view. Not applied in the loader (F-007), `v_item_outstanding` (F-008), or the strategy document (F-041) |
| 6 | Exclusion-rule semantics restricted | Loader only | Exclusion semantics await clinical approval (OC-4). A CHECK is possible but missing (F-034). The loader does not check `kind` or `machine_evaluable` (F-007) |
| 7 | Refusal, withdrawal, no-permission and declined referral are not conflated | DB plus trigger | Consent `state` CHECK, `closed_refused` forbidden for referral gaps, `refused` removed from event statuses. The reserved suppression reasons are free text (F-018) |
| 8 | D2 remains provisional | Doc | Tagged throughout with sub-questions S1–S5. Tagging inconsistencies on `patient` and `referral` (F-041). What D2 blocks is contested (F-003) |
| 9 | D18 safeguards without a legal-sufficiency claim | DB plus trigger | Outreach CHECK requires a consent FK unless suppressed; the marker FK proves a `granted` permission of the right type. Non-sufficiency is stated at design L763 and L1416. Governance and legal review is outstanding |
| 10 | LLMs do not determine eligibility, diagnosis, thresholds or risk | Privileges plus Doc | No document names LLMs. AI output is confined to separate columns with separate grants. Nothing in the database stops the engine role being an LLM pipeline. `priority_explanation` is free text. Documentation-only (F-043) |
| 11 | Outreach and person-level AI scoring are permission-gated | DB plus trigger | Consent FKs and the trigger. A human-approval requirement for AI-triggered outreach is representable but not mandated, and whether the responsible-AI standard requires it is UNVERIFIED (F-018) |
| 12 | Synthetic records cannot be mistaken for real | DB | `is_synthetic` CHECK, `SYNTH-` key CHECKs on all 18 tables, Emirates-ID anti-pattern CHECK, `@example.invalid`, separate schema. Free-text staff and reviewer tokens, and the phone pattern, have no CHECK (F-040). Real facility names (D1) are a governance item |

**Gaps between written safeguards and enforcement:** items 4, 5, 6 and 10 are the substantive ones.

---

## 7. Source-data and reconciliation consistency

### 7.1 Verified facts

| Check | Result |
|---|---|
| `shasum -a 256 -c data/reference/raw_checksums.sha256` | **215/215 OK**, 0 failures |
| Manifest and acquisition-report checksums (SRC-10, SRC-11, SRC-19, SCAD workbooks) | Match actual files |
| Processed CSV hash vs `quality_report.json` `output_sha256` | Match |
| Raw file counts (5 + 158 + 10 + 42) and 14,913 API rows | Match all documents |
| Projection indicators | Exactly 4866, 4868, 4869, 4870; 4867 not held |
| Facility register | 5,339 features; `CH_FID` present and distinct on all 5,339 |
| Bed capacity | `"0"` 2,586, `""` 2,208, `null` 434, positive 111 |
| Licence status | 14 non-null values, with a typo variant kept separate (15 keys including blank) |
| `geo_quality` | 5,299 / 31 / 6 / 3 recomputed with the documented box |
| Hospital counts | 71 Active, 74 Active+About to expire, 114 all |
| SDI retrieval stamp | 2026-11-14 (the tool-recorded value) |
| IFHAS eligibility inferred from THIQA/BASIC/ENHANCED `N/A` | **No document does so.** The restriction is stated consistently |

### 7.2 Not independently verified

- **42 single-dimension and 479 multi-dimension mismatches, and the +10,940.** Documents agree on every breakdown (33 + 4 + 4 + 1 = 42; 299 + 128 + 52 = 479; 4,379 + 479 = 4,858). The values were not recomputed, as instructed. The multi-dimension screening script lives only in a session scratchpad outside the repository, so nobody can reproduce it from the repo (F-045).
- Whether the SDI fetch altered anything beyond adding a `_source` envelope (F-044).
- The 2022 workbook re-fetch. No provenance record exists (F-046).

### 7.3 Inconsistencies

| Topic | Where the documents disagree |
|---|---|
| +10,940 | The manifest (SRC-17, L687) and the data dictionary §4 still say "disclosure rounding"; the reconciliation report, design and quality report say rounding cannot explain it (F-027) |
| Totals reconcile | The acquisition report (L86, L314) says totals "sum exactly" on every indicator tested, against 42 and 479 non-reconciling cells (F-027) |
| Projected vs observed | The acquisition report §8 mixes estimates and projections and omits 4866. The data dictionary does not mark the four as projections (F-028) |
| Age-label corruption | Four documents say "4868, two labels"; the mapping finds three labels across four indicators (2584, 3276, 3535, 4868) (F-028) |
| Regional birth cohorts | The data dictionary offers regional cohorts from 1977; no regional split exists before 2010 (F-028) |
| `geo_quality = ok` | The acquisition report and quality report say "clean" or "inside Abu Dhabi"; the design says the bounding box only (CD-11) (F-047) |
| Raw vs corrected coordinates | The data dictionary does not say the 3 `out_of_bounds` rows keep the bad pair in the CSV, nor that swapped rows are overwritten in place (F-047) |
| Bed capacity type | The data dictionary §6, quality report and transform still say "integer" or "plain integer" (MC-15 left open) (F-047) |
| Facility personal data | Manifest SRC-18 says "no personal data"; other documents say it carries named individuals' contact details (F-048) |
| `CH_FID` format | The reconciliation report omits the `_nnnn` segment; the actual form is `DOH_dd_mm_yyyy_nnnn#n#n` (F-047) |
| Retrieval vs repository-copy dates | Manifest `downloaded: 2026-11-15` for the SCAD API and other sources equals the repository-copy time, the same issue that proved wrong for SDI. The design reads one manifest field as retrieval in one place and as copy in another (F-014b below) |
| Provenance | The manifest was edited in commit `4733e6d` while `manifest_version` stayed `2.0.0`, although the design says no YAML or data changed (F-027b) |
| Orphan workbook | `scad_health_tables_en.xlsx` has no manifest entry, contradicting the README rule. The design registers 215 files, the mapping 214 (F-030) |
| Processed CSV | The mapping calls it "committed", but it is git-ignored. Only the report JSON is committed (F-049) |

---

## 8. YAML-to-database mapping assessment

### 8.1 Counts (VERIFIED by parsing the YAML and calling the loader)

| Quantity | YAML | Loader | Mapping | Design | Agree? |
|---|---|---|---|---|---|
| Rules | 54 (IFHAS 29, Well-Child 25) | 54 | 54 | 54 | Yes |
| Authoritative / non-authoritative | 47 / 7 | 47 / 7 | 47 / 7 | 47 / 7 | Yes |
| Review-flagged | 7, all real booleans | 7 | 7 | 4 verified-and-flagged + 3 unresolved | Yes |
| Rule items | 249 = 174 Well-Child + 75 IFHAS package components | 174 only | 249 | 174 + 75 | Yes. The loader gap is intentional (mapping L269) |
| Unresolved items | 9 | 9 | 9 | 9 | Yes |
| Open questions | 23 | 23 | 23 | 23 | Yes |
| Rule-question links / item-question links | 69 / 15 | — | 69 / 15 | — | Yes |
| Conditions | 8 (5 inclusion, 3 exclusion) | not validated | 8 | 8 | Yes |

### 8.2 Boolean and null parsing

- The loader reads the review flag with plain `bool(raw.get("requires_clinical_review", False))` at `loader.py:230`. This was checked on scratch copies of the YAML.
- `null`, `""`, `0`, `[]` and a missing key all become `False`, so a review-flagged rule loads as authoritative with no error.
- The strings `"false"`, `"no"` and `"0"` become `True`. This fails safe.
- No other flag is type-checked: `machine_evaluable`, `one_time`, `is_diagnosis`, `is_screening_result_only`, `may_drive_decisions`.
- No test covers a string, null or missing value.
- Today all 54 values are real booleans, so the defect is latent. The design and mapping require strict, mandatory parsing in the future database loader (LV-1); the existing loader, described as the validation authority, does not do it. See F-005.

### 8.3 Authority

| Path | Result |
|---|---|
| Review-flagged rule via loader | **Can become authoritative** by a one-character YAML edit (F-005) |
| Item under a flagged rule via loader API | `require_authoritative()` passes. Latent, because 0 items sit under non-authoritative rules today (F-007) |
| Item under a flagged package via `v_item_outstanding` | The 6 `package_component` rows under the 4 flagged packages would count as outstanding (F-008) |
| Unresolved item | **No path found** to authority. Both the loader and the design key off item status |
| Design `rule.requires_clinical_review` default | `DEFAULT false` reopens the same path at schema level (F-006) |
| Proposed effective-authority view | Correct as written; join type UNVERIFIED. Left joins could produce `NULL` that consumers misread (F-041) |

### 8.4 Loader-to-design incompatibilities (F-017)

The design depends on a second raw parse for fields the loader does not return: item ordinal, `code_origin`, `text_verbatim`, `inherited_from_rule`; open-question resolution fields; source publisher and page fields; and `rule_load.config_versions` (only 2 of the 4 keys captured). Probes showed the loader also accepts `clinical_review_status: approved` where the mapping requires a mismatch to fail, an open-question `status` of any string, and `may_drive_decisions: "true"` as a string. Two parsers can diverge.

### 8.5 Other

- `Rule.unresolved_items` includes `reported` items, so "9 unresolved" can be misread (F-050).
- List fields are coerced with `tuple()`; a string becomes a tuple of characters (F-050).
- No test pins the global counts (F-050).
- The mapping table at L172 has a malformed row, and `docs/clinical-rules.md` L61–63 documents `requires_clinical_review` as optional (F-050).
- The mapping states 4 open questions are cited by no rule: `EXPANSION-2025`, `CCHD-VISIT`, `GOV-DATA-RESIDENCY`, `GOV-CLINICAL-VALIDATION`. This is consistent.

---

## 9. Technical feasibility assessment

**Feasibility: implementable on PostgreSQL 16 with SQLAlchemy 2.x and Alembic, with these constraints.**

| Topic | Assessment |
|---|---|
| Schemas, tables, composite and generated-column FKs | Standard PostgreSQL. Composite FKs that include stored generated columns on both sides are asserted by the design as working (design U8). **UNVERIFIED** in this audit. It should be verified in the first migration, as the design itself says |
| SQLAlchemy 2.x | Composite FKs, `Computed(persisted=True)` columns, CHECKs and `schema=` are supported. Views, triggers and constraint triggers are not model constructs; they need Alembic `op.execute` or the replaceable-objects pattern |
| Alembic | Autogenerate does not detect CHECKs reliably or any trigger, view or privilege. The design needs a naming convention (D7 sets one), and manual migrations for triggers, views and role grants |
| Roles and privileges | `GRANT` / `REVOKE` per column and per table are needed for the append-only and AI-score separation. These live in migrations, not in models |
| Triggers required | Consent currency and scope, child and guardian rules, closing-evidence timing, facility-profile usability, same-run provenance of rule bundles, and the append-only guards. Nine to twelve distinct trigger functions are implied |
| Views required | `v_observation_leaf`, `v_observation_current`, `v_derived_total_additive`, `v_indicator_year_shape`, `v_facility_usable`, `v_rule_current`, `v_rule_authority`, `v_rule_item_effective_authority`, `v_eligibility_current`, `v_consent_current`, `v_item_outstanding` |
| Application or loader validation | Parsing, reconciliation classification, coordinate repair and equivalence, strict booleans. The loader must be extended before it can serve as validation authority (F-005, F-007, F-017) |
| PostGIS (D6) | Not needed. A plain `DOUBLE PRECISION` pair with CHECKs is feasible. PostGIS is not required by any current query |
| Purge job (F-021) | A specified purge role is needed for synthetic-run deletion. Without it, the append-only triggers make deletion impossible |

**Not created or run in this audit:** no database, migration, model, SQL script or infrastructure.

---

## 10. Consolidated unresolved decision register

The register covers D1–D18, D-P1, CD-1–CD-11, MC-1–MC-16 and outstanding open questions. **No item is marked approved merely because a recommendation exists or a document was changed.**

**Approval evidence caveat.** Every "approved" status below is ASSERTED. The design says the owner approved D1, D8, D16, D18 and the corrections CD-3 to CD-11 (design L6, §13). The repository holds no approver name, date or record, and the "Step 4 final report" that the reconciliation report cites (L842) is absent.

**Blocking key.** **P4** blocks Phase 4 schema implementation. **EVAL** blocks clinical evaluation or authoritative outputs. **PROTO** is safe to leave open for a labelled synthetic prototype. **PROD** is a production, compliance or deployment item.

### 10.1 D1–D18 and D-P1

| ID | Title | Documented status | Recommendation or decision | Blocks | Approver needed | Reference |
|---|---|---|---|---|---|---|
| D1 | Real facilities with a synthetic capability overlay | "APPROVED" (design L1184, L1203); governance review "not obtained" | Real SDI names; simulated `offers_*` in `facility_service_profile`; UI labels "simulated" | P4: no. Profile creation is blocked by D13. PROD: governance review | Governance/legal | Design §8 D1; §5.2 L777 still words it as open |
| **D2** | Refusal representation | "PROVISIONAL — clinical approval required (not approved)" (L1214); "must not be recorded as approved until S2–S5 are answered" (L1235) | Refusal recorded once: item-level in `component_result`, no-event refusal in scoped `consent`. `refused` removed from event statuses | **P4: contested (F-003).** EVAL: yes | Clinical; product; governance/legal; ADPHC (`OQ-WCV-REFUSAL-STATE`) | Design L1185, L1214–1235; mapping CU-1; strategy L304, L336 |
| D2-S1 | Scoped consent as home for no-event refusal | Open | Consent scoped by pathway or rule | P4 (could move an entity) | Product; clinical | Design L1229 |
| D2-S2 | Valid refusal evidence | Open | Documented plus signature (plus guardian for a child's visits) | EVAL | Clinical | Design L1230 |
| D2-S3 | Patient-wide refusal as closing evidence | Open | No; must name a pathway or rule | EVAL | Clinical | Design L1231 |
| D2-S4 | Declined referral equals refusal? | "Unresolved" | `closed_refused` forbidden for referral gaps | EVAL; P4 (entity placement) | Clinical; product | Design L1232 |
| D2-S5 | Which guardian may refuse | Open | Any of the child's own guardians | EVAL; PROD | Clinical; governance/legal | Design L1233 |
| D3 | Meaning of SCAD `-` and `:` | Open | Store the raw marker, value NULL | PROTO (API load has 0 markers) | SCAD | Design §8 D3 |
| D4 | Age-label correction | Open | Detect by pattern; mark `pending`; apply after SCAD confirms | PROTO; blocks use of age bands for 2584/3276/3535/4868 | Owner; SCAD | Design §8 D4 |
| D5 | Duplicate 3422 | Open | Load both flagged, partial unique index | PROTO | SCAD | Design §8 D5 |
| **D6** | PostGIS vs plain coordinates | "RECOMMENDED — awaiting owner confirmation" (L1189, L1280); "Open" in §9.2 (L1446) | Plain `DOUBLE PRECISION` coordinates; keep `postgres:16-alpine` | **P4: yes, before the first migration** | Owner (technical) | Design §8 D6; §9.2 |
| **D7** | Migration tool | "RECOMMENDED — awaiting owner confirmation" (L1190, L1293); "Open" in §9.2 | Alembic with SQLAlchemy 2.x | **P4: yes, before the first migration** | Owner (technical) | Design §8 D7; §9.2 |
| D8 | Generation-run provenance | "APPROVED" (L1191) — ASSERTED | One immutable `generation_run`; `run_id` and `is_synthetic` on every row | P4: no | None external | Design §8 D8 |
| D9 | Workbook loading and re-fetch | Open | API only in the MVP; `source_file_id` is part of row identity | PROTO. Interacts with F-009a and F-010 | Owner | Design §8 D9 |
| D10 | IFHAS component codes | Open; "PROVISIONAL: D10" | Loader-derived slug (`code_origin = derived_slug`) | P4: low (a later switch is a primary-key data migration) | Owner; rules owner | Design §8 D10; mapping CU-2 |
| **D11** | Evaluation history | "RECOMMENDED — awaiting owner confirmation" (L1194); "Not formally approved (treated as decided)" (L1445) | Append-only plus `v_eligibility_current` | **P4** for `eligibility_evaluation`. The view needs revision (F-009) | Owner | Design §8 D11 |
| D12 | Working-day calendar | Open | Conditional `official.working_calendar`; no hard-coded weekend | PROTO for schema; EVAL for referral deadlines and weekend slots | Owner; ADPHC | Design §8 D12; mapping OU-9 |
| **D13** | Licence-status mapping | Open (design L1196); strategy "external clarification"; reconciliation "owner decision, not clinical, not publisher" | `is_operating NULL` until confirmed | P4 for DDL: no. **Blocks synthetic data generation (F-013)** | Owner; DoH licensing advisable | Design §8 D13; reconciliation OP-D2 |
| **D14** | Rule applicability policy | Open; "PROVISIONAL: D14" | Structural classes by `rule_type`; "not applicable = no row" | **EVAL.** P4: no | Clinical; owner | Design §8 D14, L622–629 |
| D15 | Facility vintage and coordinates | Open | `retrieved_at` separate from `source_effective_date`; raw GeoJSON through the repair function | P4: no. Interacts with F-009b. Blocks the facility loader's equivalence test | Owner | Design §8 D15 |
| D16 | Six additional entities | "APPROVED" (L1199) — ASSERTED | Rule load, verification status, guard, item-question link, evaluation run, evaluation reason | P4: no | None | Design §8 D16 |
| **D17** | Evaluation-contract gaps | Open; "APPROVED: D16; OPEN: D17" | Store but do not decide: record every fired guard; `partial` ⇒ review or unknown; nullable `look_ahead_days` | **EVAL.** P4: no | Clinical (precedence, `partial`, age convention); owner (look-ahead) | Design §8 D17, L1397–1406 |
| D18 | Consent defaults | "APPROVED (safest default)" (L1201) — ASSERTED; governance review "not obtained" | No explicit, current permission ⇒ no outreach or AI scoring | P4: no. **PROD: governance/legal review** | Governance/legal | Design §8 D18 |
| **D-P1** | `retrieved_on DATE` vs leaving `retrieved_at` NULL for 157 SCAD files | Open in the design (L220, L1380, L1619); "PROPOSED" in the reconciliation report (L396); missing from the strategy's register | No recommendation chosen | PROTO for a single vintage; P4 only if a column is added, so decide before the first migration. Blocks a second vintage (F-009a) | Owner | Design L220; reconciliation L396 |

### 10.2 CD-1 to CD-11

The reconciliation report (§4, L507) still says "PROPOSED; none applied". The design (§13.1) says the corrections were applied as "owner-approved". The design (§13.4, L1625–1627) asks the owner to confirm the exact names of CD-1, CD-7 and CD-10. This audit treats the statuses as ASSERTED where applied and as not approved where the design says "not applied".

| ID | Change | Design status | Still open | Blocks | Approver | Reference |
|---|---|---|---|---|---|---|
| CD-1 | Item authority view `v_rule_item_effective_authority` plus `status_is_verified` | Applied (L581–595); name unconfirmed | Name; downstream views and loader not yet aligned (F-007, F-008, F-041) | P4 for `rule_item` DDL until the name is confirmed | Owner | Design L581–595, L1627 |
| CD-2 | Link `effect` class and cited/derived marker | **"Not applied"** (L1596, L608) | Everything | **EVAL.** P4 only if approved (adds a column) | Clinical/rules owner (OC-1) | Design L608 |
| CD-3 | Authority glossary and third condition | Glossary applied; third condition "not in the formula" (L1597) | Third condition; glossary wording (OC-6) | EVAL | Owner; clinical | Design L436, L441 |
| CD-4 | `kind` CHECK and exclusion semantics | CHECK applied (L557); semantics "pending clinical approval" (L565) | Semantics; no machine-evaluable exclusion (F-034) | EVAL | Owner (CHECK); clinical (semantics) | Design L557–565 |
| CD-5 | 14 non-null licence statuses | Applied | None | — | Owner | Design L380 |
| CD-6 | Projection set kept out of observed views | Applied | None | — | Owner | Design L270 |
| CD-7 | Reconciliation classified, never asserted | Applied; name unconfirmed | Stale wording in the official ERD (F-024) | — | Owner | Design L340, L1627 |
| CD-8 | Bed-capacity string states | Applied | Publisher meaning (OP-D3) | — | Owner; DoH | Design L384 |
| CD-9 | Four time concepts | Concepts applied | D-P1 undecided | See D-P1 | Owner | Design L223–232 |
| CD-10 | `facility.ch_fid` raw TEXT, UNIQUE NOT NULL | Applied; name unconfirmed | Vintage-awareness (F-009b) | P4 for DDL until confirmed | Owner; DoH (OP-D1) | Design L373, L400, L1627 |
| CD-11 | `geo_quality = ok` means inside the bounding box | Applied | None. Other documents still say "clean" (F-047) | — | Owner | Design L389 |

### 10.3 Mapping corrections MC-1 to MC-16

Fifteen of the sixteen were applied in their target files (checked against the files by line). **MC-15 (bed-capacity "plain integer" in `quality_report.json` and `build_facilities.py`) is not applied**, as the reconciliation report itself left it out of scope. No document gives any MC item an approval status, and the reconciliation report was not updated after they were applied, apart from an appended addendum (L842).

### 10.4 Other outstanding items

| ID | Item | Default until decided | Blocks | Approver |
|---|---|---|---|---|
| OC-1 | Effect classes per rule-question link | Formula unchanged; cited questions shown | EVAL | Clinical/rules |
| OC-2 | "Ever smoked" definition for `IFHAS-PKG-AAA-M-65-75` | `insufficient_information` when absent | **EVAL.** The rule counts as authoritative and machine-evaluable while resting on an undefined term (F-015) | Clinical |
| OC-3 | FIT and colonoscopy flagging versus liquid biopsy | Unchanged | EVAL | Clinical |
| OC-4 | Exclusion semantics and combination logic | No machine-evaluable exclusion | EVAL | Clinical |
| OC-5 | Sex gate `IFHAS-PROG-ELIG-SEX-BY-PACKAGE` | Unchanged | EVAL | Clinical |
| OC-6 | Glossary wording of "authoritative" | Proposed wording used | — | Owner; clinical |
| OP-S1 to S6 | SCAD: pre-2010 zero leaves; 2024 +10,940; 4867; residuals; age labels and 3422; orphan workbook | Report-classified; nothing fixed | PROTO; EVAL for pre-2010 regional cohorts and 2024 age bands | SCAD |
| OP-D1 to D4 | DoH: `CH_FID` meaning; operating statuses; bed `""` vs `"0"`; register publication date | Raw kept | OP-D2 gates D13 | DoH Abu Dhabi |
| OP-A1 | ADPHC: do the age, sex and frequency questions apply to every package | — | EVAL | ADPHC |
| CA-4 / LV-4 | `affects` expansion into derived links | Not built | **EVAL** | Loader; clinical |
| CU-6, CU-7, CU-8 | `rule_reported_not_verified` produced by no guard; no column for the YAML overdue note; 2–4 week range not representable | Open | EVAL; CU-7 P4 if a column is added | Owner; clinical |
| CU-18 | Guard nullability | Mapping: NOT NULL. Design and ERD: "not stated" | P4 for DDL (F-042) | Owner |
| OU-10, OU-11 | `measure_kind` and `region_basis` seeds | `unclassified`; nothing additive | Blocks additive views | Data steward; SCAD |
| OU-14 | Orphan workbook | Not registered | 1 of 215 files (F-030) | Owner |
| OU-15 | Attribution, `fit_for_use`, `contains_data` have no manifest source | NULL | PROD (licence attribution) | Owner; legal |
| U1 | AI re-score overwrites the previous score | — | PROD (AI audit trail) | Owner |
| U5 | Gap reopening after a superseded refusal | — | EVAL | Clinical; engine |
| U8 | Generated-column composite FKs in SQLAlchemy | Verify in the first migration | P4 | Technical |
| EX-1 | Challenge data-use rules were never read | — | **PROD, and plausibly the prototype** (F-014c) | Challenge organiser |
| EX-2 | Data residency | No real data anywhere | PROD | Architecture; DoH |
| EX-3 | Clinical validation and AI risk classification | `not_reviewed` | **EVAL and PROD** | Healthcare partner; DoH |
| EX-4 | Consent categories and lawful basis | D18 default | PROD | Governance/legal |
| EX-5 | Fairness metrics | — | PROD | AI governance |
| EX-6 | Clinical decisions on timely, overdue and refusal | — | EVAL | Clinical |
| EX-7 | Community and cultural review | — | PROD | Community partner |

### 10.5 Separation by blocking class

**A. Blocks schema implementation (Phase 4 DDL):**
- D6 and D7 confirmation.
- CD-1, CD-7 and CD-10 name confirmation, and CU-18 nullability.
- The D2 scope decision (F-003) for the synthetic schema.
- D11, plus a revised `v_eligibility_current` (F-009), for `eligibility_evaluation`.
- D-P1, if option (b) is chosen.
- The facility-key and `v_observation_current` decisions (F-009a, F-009b).
- Dropping `DEFAULT false` on `requires_clinical_review` (F-006).

**B. Blocks clinical evaluation or authoritative outputs:** D2 sub-questions S2–S5, D14, D17, CD-2 / OC-1, OC-2 (AAA rule), OC-3, OC-4, OC-5, CA-4 / LV-4, D12, CU-6 and CU-8, EX-3, EX-6.

**C. Can remain open for a labelled synthetic prototype:** D3, D4, D5, D9 (single vintage), D10 (slug), D15 (single vintage), OU-10, OU-11, OU-14, OP-S1 to S6, OP-D1, OP-D3, OP-D4.

**D. Production, compliance and deployment:** D1 governance review, D18 legal review, D2-S5, EX-1 (see F-014c), EX-2, EX-4, EX-5, EX-7, OU-15, U1.

**Blocks synthetic data generation in practice:** D13 (F-013).

---

## 11. Findings

### Severity key

- **Critical (gating):** prevents implementation of a bounded area until resolved.
- **High:** can produce a wrong clinical, consent or authority result, or contradicts the design's own principles at a point that determines DDL.
- **Medium:** integrity, provenance or documentation defects that an implementer would plausibly follow.
- **Low or Info:** editorial, minor, or recorded positive checks.

"Owner approval" names who must approve the resolution. Findings that were merged keep the original IDs in brackets for traceability (A1 official schema, A2 clinical and synthetic, A3 source, A4 YAML and loader, A5 decisions and ERDs).

### 11.1 Critical

| ID | Ref | Inconsistency or gap | Why it matters | Resolution | Owner approval |
|---|---|---|---|---|---|
| **F-001** | Design §8 D6, D7 (L1189–1190, L1280, L1293) vs §9.2 (L1446); [A5-005] | D6 and D7 are "RECOMMENDED — awaiting owner confirmation" in §8 and "Open" in §9.2. Alembic and SQLAlchemy 2.x are assumed throughout. | No migration can be created before the migration tool and the coordinate type are fixed | Owner confirms D6 and D7 in writing; use one status term | **Yes — owner (technical)** |
| **F-002** | Design §13.4 (L1625–1627); [A5-004] | CD-1, CD-7 and CD-10 names are not confirmed. CD-10 makes `facility.ch_fid` UNIQUE NOT NULL on a recommendation the reconciliation report phrased as "Consider". CU-18 nullability is unresolved | Constraint names and nullability become DDL | Owner confirms by name; align the reconciliation report status (it still says "none applied") | **Yes — owner** |

### 11.2 High

| ID | Ref | Inconsistency or gap | Why it matters | Resolution | Owner approval |
|---|---|---|---|---|---|
| **F-003** | Design §9.2 L1444 vs strategy §13 L336; design L1223, L1437; [A5-001] | The design says D2 blocks "refusal triggers and the generator; not the schema skeleton". The strategy says "Do not implement refusal triggers, the engine or any synthetic table until D2 is clinically approved". The design also says the synthetic ERD is "Pending D2". | Phase 4 cannot tell whether the 18 synthetic tables may be migrated | Owner decides: (a) no synthetic DDL until D2, or (b) provisional DDL with D2 expressions flagged. Align both documents | **Yes — product owner; clinical for D2 itself** |
| **F-004** | Design L520, L795–815, L944; [A2-001] | No database mechanism stops `eligible`, `due`, `overdue`, `completed`, `not_eligible` or `upcoming` being recorded against a non-authoritative rule (7 rules, 3 unresolved). Only the engine guard and R-C5 prose prevent it. `care_gap` inherits the gap | This is the central safeguard "unresolved rules cannot produce authoritative results", and it is engine behaviour only | Apply design §2.5's marker-FK pattern: a generated `needs_authority` column and a composite FK to `rule(…, is_authoritative)`. Clinical owner agrees the decisive set | **Yes — design owner; clinical owner for the decisive set** |
| **F-005** | `data-pipeline/rule_loader/loader.py:230`, `models.py:39, 132`; tests; [A4-001, A4-002] | `bool(raw.get("requires_clinical_review", False))`. A null, empty, `0`, `[]` or missing value loads a review-flagged rule as authoritative with no error (checked on scratch copies). No test covers non-boolean or missing values | Latent today (all 54 values are real booleans), but one edit promotes a flagged rule. The design's strict-parsing requirement (LV-1) is only planned for the future DB loader | Make the key mandatory and `isinstance(v, bool)` in `load_rules()`; add parametrised negative tests for every flag | **No** (loader developer) — but clinical owner informed |
| **F-006** | Design L519 vs L131, L153 and L1136; mapping L172; [A2-002, A4-004] | `rule.requires_clinical_review BOOLEAN … DEFAULT false`, against "no default is invented" and "absent key rejected, never coerced". `is_authoritative` is generated true when the status is `verified` | An INSERT that omits the column silently produces an authoritative rule | Remove the default; keep NOT NULL | **Yes — design owner** |
| **F-007** | `models.py:106–115, 160–166`; `loader.py:164–175, 236–242`; [A4-003, A4-008, A4-012] | Loader item authority uses the item's own status only, so a flagged parent still gives `require_authoritative()` a pass (confirmed on a scratch copy of `WCV-VISIT-12M`). The loader does not check `kind`, `machine_evaluable` on exclusions, `may_drive_decisions` strings, or `clinical_review_status`. It does not return many fields the design loads | The CD-1 parent-aware fix exists only in the design. The loader is described as the validation authority, so it accepts content the DB design rejects | Add a parent reference or return no authoritative items when the rule is non-authoritative; rename to `status_is_verified`; extend validation to everything the DB loads | **No** (loader); design owner confirms naming |
| **F-008** | Design L892 vs L581–595; [A2-008, A4-005] | `v_item_outstanding` excludes only items whose own `verification_status` is not `verified`. The 6 component rows under the 4 flagged packages would appear as outstanding | Bypasses the parent-aware authority view for a patient-facing output and could drive `partial_completion` gaps under non-authoritative rules | Define it over `v_rule_item_effective_authority` | **Yes — design owner; clinical for how flagged packages surface** |
| **F-009** | (a) Design L344, L1312, L220, L1612; mapping L125. (b) Design L372–374, L400, L56; mapping L411, OU-17. (c) Design L812, L628, L1340; [A1-006, A1-008, A2-015] | **(a)** `v_observation_current` picks the latest `source_file` by `retrieved_at`, which is NULL for all 157 SCAD files, so it orders nothing. Only the mapping adds a guard. **(b)** Facility uniques (`source_layer`+`source_object_id`, `license_no`, `ch_fid`) exclude `source_file_id`, so only one register version can load, contradicting "new vintage = new rows". **(c)** `v_eligibility_current` takes the latest row per (patient, rule) across runs. A later run that produces no row (not applicable) leaves the earlier result visible, against "no row means not applicable" | The default read paths misbehave exactly where the vintage and absence principles apply | (a) Put the mapping's guard in the design or choose another ordering key (D-P1). (b) State "single vintage in MVP" or add `source_file_id` to the keys. (c) Define current state as rows of the latest **completed** evaluation run | **Yes — design owner (D9, D11, D15, D-P1)** |
| **F-010** | Design L665–693; [A2-016] | `evaluation_run` has no completion marker. `generation_run` has `finished_at`, but nothing checks it | Rows from an aborted engine run cannot be told from a complete run; views would read them | Add `finished_at` (and status) to `evaluation_run`; views use finished runs only | **Yes — design owner** |
| **F-011** | Design L851, L853, L970; [A2-017] | A `partial` screening has `has_performed = true`, so it is valid completion evidence. A `closed_completed` gap may cite a partial screening, including the one the gap is about | A gap can be closed as complete by evidence that is incomplete | Use a generated `is_complete` marker; add a CHECK so a `partial_completion` gap cannot be closed by its own subject screening | **Yes — design owner; clinical owner** |
| **F-012** | Design L966–976; [A2-018] | Closing evidence is under-constrained: `closed_by_referral_id` need not equal `subject_referral_id`; a screening dated before the gap can close it; a cited referral can later become `declined` | Gaps can close on unrelated or later-reversed evidence | CHECK for the referral match; trigger for dates; freeze a cited referral or include status in the marker | **Yes — design owner** |
| **F-013** | Design L776, L843, L864, L1016, L1210; reconciliation L672, L717, L779; [A5-002] | `ifhas_screening`, `well_child_visit` and `appointment` need a NOT NULL `profile_id`. No profile can exist until D13 confirms a licence status. The reconciliation report suggests "clearly fictional profiles", but the approved D1 schema has no fictional-facility path | No care event can be generated until D13 is decided, or D1 is amended | Decide D13 (at least one `confirmed` status) or formally amend D1; remove the fictional-profile option from the report unless supported | **Yes — owner; DoH licensing advisable** |
Governance and provenance findings F-014a to F-014c follow in 11.3.

### 11.3 Governance and provenance findings

| ID | Sev | Ref | Inconsistency or gap | Why it matters | Resolution | Owner approval |
|---|---|---|---|---|---|---|
| **F-014a** | High | Design L6, §13, L1203; reconciliation L842; [A5-003] | The owner's approvals of D1, D8, D16, D18 and CD-3 to CD-11 are recorded only inside the design. No approver, date or ticket exists, and the "Step 4 final report" is not in the repository | Approvals cannot be audited; the register's "approved" entries are ASSERTED | Add an approval log (who, when, scope) or link the external record | **Yes — owner / governance** |
| **F-014b** | Medium | Design L232, L1612–1613; manifest L356, L406, L644, L797, L857, L895; [A1-028, A3-017] | The manifest `downloaded` field is read as a retrieval date in one place and a repository-copy date in another. The copy date is given as one day (2026-11-15) but is two (2026-11-14 and 2026-11-15). For SRC-17, 19, 20 and 21 the "2026-11-15" equals the repository-copy mtime and no log carries a timestamp, the same defect that proved wrong for SDI | The retrieval-versus-copy distinction is enforced for SDI only | Annotate each manifest entry as "date claimed, not tool-recorded"; define the field's meaning; decide D-P1 | **Yes — data owner** |
| **F-014c** | Medium | Reconciliation L650, L795, L801; [A5-012] | EX-1 / GAP-8: the challenge's data-use rules were never read | This may constrain even the prototype's use of official data and real facility names (D1), not only production | Read the rules before any demo that uses D1 | **Yes — governance/legal** |

### 11.4 Mixed severity — clinical, loader and source-document findings (severity is stated per row; F-027 is High, the rest Medium)

| ID | Sev | Ref | Inconsistency or gap | Why it matters | Resolution | Owner approval |
|---|---|---|---|---|---|---|
| **F-015** | Medium | Design §10 #12 L1502; reconciliation L133; [A5-019] | `IFHAS-PKG-AAA-M-65-75` is authoritative and machine-evaluable but rests on the undefined term "ever smoked" (OC-2) | An authoritative output rests on an unresolved definition | Treat as an EVAL blocker until OC-2 is decided | **Yes — clinical** |
| **F-016** | Medium | Design L548, L666, L685, L1340; mapping CLIN §2; [A2-005, A2-006] | The rules that make up each `rule_load` are not stored (`rule.load_id` records only the first load). A rule removed from the YAML makes every later load FATAL, so rules can never be retired | Evaluation provenance cannot be checked against its run's bundle; `v_rule_current` cannot be computed "as of" a bundle | Add a bundle-membership table and a retirement path | **Yes — design owner; rules owner** |
| **F-017** | Medium | `models.py:91–104, 189–208`; `loader.py:301–305`; mapping §1; [A4-012] | The design needs a second raw parse for fields the loader does not return, and two parsers can diverge. `rule_load.config_versions` needs 4 keys; the loader captures 2 | Divergence between two readings of the same YAML | Extend `load_rules()` to everything the DB loads, or add tested raw validators | **No** (loader); design owner |
| **F-018** | Medium | Design L723–763, L988, L1037, L1043, L1046, L1048; [A2-023, A2-024, A2-027, A2-028, A2-029] | Consent and outreach: (a) overlapping scopes have no precedence (a patient-wide `granted` row and a later pathway-scoped `withdrawn` row are both current); (b) child-specific rules (outreach goes to the guardian; consent from a guardian) are missing from §6.3; (c) outreach `opted_out` has no defined link to a `withdrawn` consent; (d) the reasons that keep absence, withdrawal and refusal apart are free text; (e) AI-triggered outreach without clinician approval is representable and not mandated | These are the permission safeguards of D18 | (a) Define precedence (most restrictive wins); (b) add both rules to §6.3 #7 and #11; (c) require a `withdrawn` row; (d) use a CHECK-constrained category; (e) owner decides whether sending is forbidden and adds the CHECK | **Yes — product; governance/legal** |
| **F-019** | Medium | Design L779–791, L994, L1098, L1142; [A2-019, A2-025] | (a) The "gap-yielding" status set is undefined; a gap may cite a programme-eligibility rule, blurring eligibility and documented gap. (b) No history row has no stated meaning (should be `unknown`); history is per pathway, but gaps are per package; "latest wins" ignores the reference date | Weakens the five-way separation and the "missing history ≠ not screened" safeguard | (a) Define the status and rule-type sets and enforce by marker FK; (b) state no row = unknown; use "latest ≤ reference date"; consider rule-level scope | **Yes — product; clinical** |
| **F-020** | Medium | Design L153 (P4) vs L1096, L995; [A2-020] | P4 says history is append-only and "referrals' history is never overwritten", but care-gap lifecycle, referral status and appointment status are mutable with no history. A superseded gap has no FK to its successor | The principle and the schema contradict | Add lifecycle event tables or reword P4; add `superseded_by_care_gap_id` | **Yes — design owner** |
| **F-021** | Medium | Design L1114 vs L1096; [A2-033] | A run-purge job is described but append-only triggers reject DELETE; no purge role or procedure is specified | Synthetic runs cannot be removed, or the guarantees weaken through an unstated bypass | Specify a purge role, bypass and audit | **Yes — design owner** |
| **F-022** | Medium | Design L751, L844, L865, L910, L1130, L1137–1143; [A2-022] | Several checks documented as triggers or tests are expressible as composite FKs (see 4.3) | Triggers cost more to test and maintain than FKs | Convert to FKs or record why not | **Yes — design owner** |
| **F-023** | Medium | Design §9.1, §5.6; ERDs; [A5-013] | No synthetic ERD exists, so none of the same-run, same-patient or evidence-marker FKs is diagrammed | The most error-prone constraints have no review artefact | Draw a provisional synthetic ERD with D2-dependent entities flagged, or make one explicit decision to skip it | **Yes — owner** |
| **F-024** | Medium | Official ERD L88–101, L301, L318; design L274, L340; mapping D-4; [A1-001, A1-002, A5-008, A5-014] | The ERD omits four `indicator` columns, does not list the omission, and says nothing was omitted. It also restates "leaves sum to aggregate", which CD-7 withdrew | The ERD says it reflects rev 2.5 | Add the four columns, add a discrepancy row, reword the reconciliation line | No (ERD author) |
| **F-025** | Medium | Design L213–236; [A1-003, A5-009] | The "Four time concepts" table is inserted inside the `source_file` column table, so `contains_data`, `fit_for_use`, `loader_version` and `registered_at` render as orphan rows | An implementer could miss four columns | Move the table after the column table | No (editorial) |
| **F-026** | Medium | Design L110, L128, L407, L772; [A1-009] | `ON DELETE RESTRICT` plus the synthetic FK to `official.facility` blocks reloading facilities while any synthetic run exists (UNVERIFIED whether intended) | The official reload depends on removing synthetic data first | Document the reload order or rely on vintage-aware keys | **Yes — design owner** |
| **F-027** | High | Manifest SRC-17 L687; acquisition report L86, L314; data dictionary §4 L177; [A3-001, A3-002, A3-004] | The manifest still says the +10,940 is "disclosure rounding". The acquisition report still says totals "sum exactly" on every indicator tested. The data dictionary still frames the +10,940 as rounding | The manifest is called "authoritative"; the acquisition report is the Phase 3 readiness justification. Both repeat what the reconciliation report withdrew | Replace with "unexplained (not rounding; see OP-S2)"; limit the "reconciled" claim to 486 of 528 cells and cite 42 and 479 | **Yes — data owner** |
| **F-027b** | Medium | Design L1589 vs commit `4733e6d`; manifest L21, L718–720; [A1-029] | Revision 2.5 says no YAML or data changed. Commit `4733e6d` edited the manifest (`downloaded` dates and comments) and `manifest_version` stays `2.0.0`. The mapping's own rule is that the same version with different content fails the load | The scope statement is false, and a loader that held the old manifest would now fail | Bump `manifest_version`; correct the §13 scope sentence | **Yes — data owner** |
| **F-028** | Medium | Acquisition report §3.1, §6.3, §8; quality report A3; data dictionary §4; manifest SRC-17; mapping §7, D-7, §8.4; [A3-004, A3-005, A3-006] | Projected and observed indicators are mixed or unlabelled; the age-label corruption is described as 4868-only (2 labels) in four documents while the mapping finds 3 labels across 4 indicators; the data dictionary offers regional birth cohorts from 1977 although no regional split exists before 2010 | Zeros could be treated as observations; projections combined with estimates; 2024 double-counted | Update all documents to the mapping's verified sets | **Yes — documentation owner** |
| **F-029** | Medium | Design L199–200; mapping §2 L73–74, OU-15 L470; [A1-004] | The design says `source.fit_for_use` and `contains_data` are source-level (for example `false` for the Gov-Digital workbooks), but those are files of SRC-20, which also holds real catalogue data. The mapping sets them only at file level | A source-level `false` would be wrong | Restate as file-level, or drop the source columns | **Yes — design owner** |
| **F-030** | Medium | Design L56, L209, L1614; mapping L128, OU-14; README Rule 2; [A1-005, A3-019] | The design registers 215 files; the mapping 214. `scad_health_tables_en.xlsx` has no source and no manifest entry (the file was added with no URL or Last-Modified), contradicting README Rule 2. `source_file.source_id` is NOT NULL | The 215-row claim cannot hold | Owner assigns a source or removes the file; reword to 214 + 1 unregistered | **Yes — data owner** |

### 11.5 Medium — schema detail

| ID | Ref | Inconsistency or gap | Why it matters | Resolution | Owner approval |
|---|---|---|---|---|---|
| **F-031** | Design L174–175, L331, L154 (P6), L1132–1146; [A1-014] | `observation.row_role` is stored but derivable from ten FK columns, "asserted by test", and missing from §6.3 | The row-level copy can drift from member roles | Add to §6.3 or derive in a view | Design owner |
| **F-032** | Design L387–389, L395–398; mapping D-6 L491, §9.1; [A1-019] | `build_facilities.py` can emit `null_geometry`; the design's `geo_quality` has four values and nullable `source_*` that can never load as NULL | Documented nullability does not match loadable states | Make `source_*` NOT NULL, or add the value; record D-6 | Design owner |
| **F-033** | Design L388, L395–398; mapping §9.1; [A1-018] | CHECKs do not tie usable coordinates to raw ones for `ok` and `swapped_repaired`, and do not require them when `ok` | The raw-versus-usable relationship rests only on the loader | Add the CHECKs or record that this is loader-only | Design owner |
| **F-034** | Design L557–565, L1136 #3; [A2-011] | "No machine-evaluable exclusion" is loader-only though expressible: `CHECK (kind = 'inclusion' OR NOT machine_evaluable)`. Exclusion semantics beyond that are documented only | An in-DB guard is cheap | Add the CHECK | Design owner; clinical (OC-4) |
| **F-035** | Design L384, L383; mapping L372–373; [A1-021, A1-022] | NULL in `inpatient_bed_capacity` merges `""` (2,208) and `null` (434); `has_insurance` merges `''` (965) and unidentified. The design does not note the second | §2.2 requires every nullable column to state what NULL means | Document, or keep raw columns as is done for `is_public_raw` | Design owner; DoH (OP-D3) |
| **F-036** | Design L424, L1346; [A1-037] | `working_calendar.source` is free text, and no calendar source exists in `data/raw/` | The table would break P1 | State provenance and schema placement when D12 is decided | Design owner; ADPHC |
| **F-037** | Design L177, L1145; [A1-016] | R-O4 (no facility ↔ SCAD join or view) has no enforcement stated beyond the FK direction | "No view" is testable via `pg_depend`; "no join" only by review | Extend §6.3 #12 | Design owner |
| **F-038** | Official ERD L200–213; design L128; [A1-010] | ERD shows only the delete rule; `ON UPDATE RESTRICT` is not shown | `license_status_raw` is an FK to a natural TEXT key | Add an update column | ERD author |
| **F-039** | Clinical ERD L32–35, L295; [A2-012, A5-015, A5-016] | Link labels "blocks" and "blocked by" assert semantics CD-2 has not adopted. One edge points the `reason_code` FK at `evaluation_status`, and inbound FKs are omitted | Reads as an authority rule | Relabel "cites" and "cited by"; fix the edge | Clinical for CD-2 |
| **F-040** | Synthetic spec L3–5, L29, L85, L152, L163, L226, L261, L327; data dictionary L270–281; design L9, L1303, L1500; synthetic markers [A2-030, A2-031, A2-032] | The spec and dictionary still state the superseded contract (11 tables, `refused`, `never_requested`, per-row provenance, regenerated `screening_eligibility`) with no superseded notice. Free-text staff and reviewer tokens and the phone pattern lack CHECKs. Column tables omit `is_synthetic` | A generator built from the spec would produce rows the schema rejects | Add a "superseded by the design" banner; add the CHECKs; add `is_synthetic` to every column list | Doc owner; design owner |
| **F-041** | Strategy L253, L302; design L70, L777; [A2-009, A2-034, A4-006, A4-007, A5-007, A5-010, A5-011, A5-018, A5-021] | Strategy still says "consumer must AND" (withdrawn by CD-1) and is labelled rev 2.3. The design's view list omits `v_rule_item_effective_authority`. The design says D1 is approved while L777 still carries an open sub-question. Join type of the authority view is unspecified (UNVERIFIED). D-P1 is missing from the strategy register | Stale instructions can reintroduce the CD-1 defect | Refresh the strategy to rev 2.5; specify an INNER JOIN and `IS TRUE`; fix editorial items | Doc owner |
| **F-042** | Mapping CU-18 L396; clinical ERD §3, §9 #2; [A5-017] | Guard FK nullability is "NOT NULL" in the mapping and "not stated" elsewhere | DDL ambiguity | Owner confirms | Owner |

### 11.6 Low and informational

| ID | Ref | Finding | Resolution |
|---|---|---|---|
| F-043 | Design (no LLM mention); [A2 safeguards] | The LLM boundary is documented only through privileges and Group 3 separation | State explicitly that LLM output is confined to AI-score columns |
| F-044 | README Rule 1; SDI files; [A3-016] | SDI raw files carry a tool-added `_source` envelope and are not "byte-for-byte as served". UNVERIFIED whether anything else changed | State in the README and manifest |
| F-045 | Reconciliation §0; [A3-003] | The 42 and 479 screening script is outside the repository | Commit or specify the algorithm (for LV-10) |
| F-046 | Quality report L30–33; [A3-018] | The 2022 workbook re-fetch has no provenance record | Add a re-verification sub-record or soften the claim |
| F-047 | Acquisition report §1; quality report §3, §8; data dictionary §6; reconciliation PV-2, OP-D1; `quality_report.json:102`; [A3-008, A3-011, A3-012, A3-013, A3-023] | "Clean" for `geo_quality = ok`; the data dictionary under-describes the 3 `out_of_bounds` rows and the in-place swap; bed capacity typed "integer"; `CH_FID` pattern misquoted; the data dictionary's field count does not match the CSV (27 columns) | Align to CD-11 and the mapping; track MC-15 |
| F-048 | Manifest SRC-18 L742; quality report B7; README; [A3-015] | Manifest says "no personal data"; other documents say the register has named individuals' contact details | Amend SRC-18 |
| F-049 | Mapping §9.1 L392; README layout; `.gitignore:72`; [A3-010] | The processed CSV is git-ignored, not "committed"; the equivalence test fixture is missing on a fresh clone | Say "regenerated and verified against `output_sha256`"; fix the README and quality report counts |
| F-050 | `models.py:164–166`; `loader.py:115, 124–125, 226`; tests L241–244, L300–304; mapping L172; `docs/clinical-rules.md` L61–63; [A4-009, A4-010, A4-011, A4-013, A4-014, A4-015] | `unresolved` without the flag loads but fails the DB CHECK; `unresolved_items` includes `reported`; list fields coerced via `tuple()`; open-question links do not affect authority (CD-2 unapproved); counts not pinned by tests; mapping row malformed; `clinical-rules.md` documents the key as optional | Fix in the loader and documents |
| F-051 | Design L198, L372–376, L383, L399–400, L416, L419–421; [A1-011, A1-017, A1-020, A1-023, A1-025, A1-026, A1-027, A1-032–A1-036, A1-038–A1-041] | Minor items: ERD calibration-provenance wording; `ch_fid` per-extract caveat; `ok` meaning (consistent); `is_public` "approved" overstated; `note` required in prose but not in the CHECK; `status_group` vocabulary differs; licence date fields not modelled (D13); `validation_state` CHECK admits `clinical`; SMALLINT `region_id`; `dimension_member` NULL bounds and `correction_basis`; duplicates not protected; 24/23 co-located groups; manifest upsert overwrites history; whitespace licence number; one-directional `identity_status` CHECK | Handle with design edits |
| F-052 | Reconciliation header L4–5 vs L648, L842; [A3-007] | Header says "nothing approved" while the addendum records applied corrections | Add a revision banner |
| F-053 | Manifest SRC-12 L470; [A3-021] | The census-page pyramid sums to ~4,136,000, which suggests the +10,940 is specific to the API | Add to OP-S2 as context (UNVERIFIED) |
| F-054 | Quality report L76; [A3-022] | "10 GeoJSON extracts"; there are 9 plus a log | Fix wording |
| F-055 | Design §13.2 L1612–1613; [A3-025] | Repository-copy dates per workbook not stated per file | Give per-file dates |

### 11.7 Recorded positive checks

Checked and found consistent: table inventory across documents (A1); `ch_fid` as TEXT NOT NULL UNIQUE (A1-017); `geo_quality = ok` meaning (A1-020); bed-capacity counts across all documents (A3-009); the 42 and 479 breakdowns across documents (A3-003, UNVERIFIED against data); 14 licence values and the typo variant (A3-014); the THIQA/BASIC/ENHANCED restriction (A3-020); projection indicators 4866, 4868, 4869, 4870; checksum set; all YAML-loader-mapping-design counts (section 8.1).

### 11.8 Severity totals

Counts are of the finding IDs in this report. Several IDs (F-041, F-047, F-050, F-051) consolidate many small items from the underlying reviews, whose original IDs are cited in brackets.

| Severity | Count | IDs |
|---|---|---|
| Critical (gating) | 2 | F-001, F-002 |
| High | 13 | F-003 to F-013, F-014a, F-027 |
| Medium | 30 | F-014b, F-014c, F-015 to F-026, F-027b, F-028 to F-042 |
| Low or Info | 13 | F-043 to F-055 |

The reviewers' working files are kept only in the audit session scratchpad and are not part of the repository.

---

## 12. Phase 4 readiness verdict

### **READY WITH CONDITIONS**

Implementation may begin only in the areas below, and only after the prerequisites for each are met. This is not a READY verdict. The documentation set exists and the table counts match, but neither is the basis for it. The verdict rests on the cross-document checks, the loader and test results, and the register of decisions in sections 10 and 11.

### 12.1 What may proceed, after the prerequisites

| Area | May start? | Condition |
|---|---|---|
| Project scaffolding: SQLAlchemy 2.x / Alembic setup, naming conventions, `official`, `clinical` and `synthetic` schemas, roles | After **P-1, P-2** | Owner confirms D6 and D7 |
| `official` schema (9 tables, views, loader) | After **P-1 to P-5, P-7** | Facility key and observation-view decisions; metadata columns; `manifest_version` bump |
| `clinical` schema (12 tables) and the rule-load path | After **P-1, P-2, P-3, P-6, P-8, P-9** | Names confirmed; `DEFAULT false` removed; loader made strict and parent-aware; bundle-membership decision |
| `synthetic` schema (18 tables) | **Not yet** | Needs **P-10** (D2 scope decision), the revised evaluation views and evidence markers (F-004, F-009c, F-010 to F-012), and, for any generated care event, D13 |
| Clinical evaluation engine and authoritative outputs | **No** | D2 (S2–S5), D14, D17, CD-2 / OC-1 to OC-5, CA-4 and LV-4, EX-3 |

### 12.2 Prerequisites

| # | Prerequisite | Findings | Approver |
|---|---|---|---|
| P-1 | Owner confirms **D6** (plain coordinates) and **D7** (Alembic and SQLAlchemy 2.x) in writing | F-001 | Owner (technical) |
| P-2 | Owner confirms CD-1, CD-7 and CD-10 names, `ch_fid` UNIQUE NOT NULL, and guard nullability | F-002, F-042 | Owner |
| P-3 | Remove `DEFAULT false` from `rule.requires_clinical_review` | F-006 | Design owner |
| P-4 | Decide the facility-key vintage rule and the `v_observation_current` ordering key (D-P1) | F-009a, F-009b | Design owner |
| P-5 | Bump `manifest_version`; correct the manifest and acquisition-report statements about +10,940 and "sum exactly" | F-027, F-027b | Data owner |
| P-6 | Make `load_rules()` strict (mandatory boolean flags, parent-aware item authority, validation of fields the DB loads), with tests | F-005, F-007, F-017 | Loader developer |
| P-7 | Add the four ERD columns; fix `source_file` column-table rendering and the stale ERD wording | F-024, F-025 | Doc owner |
| P-8 | Redefine `v_item_outstanding` over `v_rule_item_effective_authority`; align the strategy | F-008, F-041 | Design owner |
| P-9 | Decide rule-bundle membership and rule retirement | F-016 | Design owner; rules owner |
| P-10 | Owner decides whether synthetic DDL may proceed under a provisional D2, and aligns the design and the strategy | F-003 | Product owner; clinical |
| P-11 | Revise `v_eligibility_current`; add an `evaluation_run` completion marker; fix the completion and closing-evidence markers; apply the decisive-status marker FK | F-004, F-009c, F-010, F-011, F-012 | Design owner; clinical |
| P-12 | Decide D13 (or amend D1) before any generated care event | F-013 | Owner; DoH |
| P-13 | Record owner approvals (who, when, scope) | F-014a | Owner / governance |
| P-14 | Produce a provisional synthetic ERD, or make an explicit decision to skip it | F-023 | Owner |
| P-15 | Mark the synthetic spec and data dictionary as superseded before building the generator | F-040 | Doc owner |

### 12.3 Not blocking Phase 4 (may stay open for a labelled prototype)

D3, D4, D5, D9 (single vintage), D10, D15 (single vintage), OU-10, OU-11, OU-14, OP-S1 to S6, OP-D1, OP-D3 and OP-D4. Production, compliance and deployment items (D1 governance review, D18 legal review, EX-1 to EX-7 other than the possible prototype impact of EX-1, OU-15, U1) are deferred, but **EX-1 should be read before any demo** (F-014c).

---

## 13. Validation commands executed

| Command | Result |
|---|---|
| `git status --short` (start of audit) | Clean |
| `shasum -a 256 -c data/reference/raw_checksums.sha256` (read-only) | 215/215 OK |
| Read-only `python3 -I -B` scripts for counts, field types, `CH_FID`, bed-capacity strings, `geo_quality` recomputation, hospital counts | All figures in section 7.1 matched |
| `PYTHONDONTWRITEBYTECODE=1 …/python3 -I -B -m pytest -p no:cacheprovider -q` in `data-pipeline/` (interpreter from a venv outside the repository, because the system Python has no PyYAML or pytest) | **80 passed** in 7.16 s (35 functions) |
| Loader probes on scratch copies of `rules/` (outside the repository) | Confirmed F-005, F-007 and the loader acceptance cases in F-017 and F-050 |
| `which mmdc`; `npx --no-install mmdc -V`; `ls node_modules/.bin`; `python3 -c 'import mermaid'` | No renderer available. Nothing installed, no network used |
| Structural Mermaid checker (scratchpad script) plus manual grammar review | No syntax defect found. **Rendering not performed** |
| `git show 4733e6d` (read-only) | Confirmed the manifest was edited while `manifest_version` stayed `2.0.0` |
| `git status --short` (end of audit) | See the final summary |

## 14. Items UNVERIFIED

- Rendering of both ERDs, and Mermaid v10 attribute syntax with the target renderer.
- Composite FKs over stored generated columns on both sides under PostgreSQL 16 and SQLAlchemy (design U8).
- The 42, 479 and +10,940 figures (not recomputed, as instructed).
- The 2022 workbook re-fetch, the age-label corruption in the multi-indicator cases, and whether the SDI fetch altered anything beyond the `_source` envelope.
- The join type of `v_rule_item_effective_authority` (no SQL exists).
- Whether the responsible-AI standard requires clinician approval of AI-triggered outreach.
- Whether blocking facility reloads (F-026) is intended.
- Whether the `""` and `null` bed-capacity states can be recovered from `identity_status`.
- Every owner approval asserted in the design (F-014a).
- The census-page pyramid sum (F-053).
