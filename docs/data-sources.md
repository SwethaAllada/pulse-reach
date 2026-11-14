# PulseReach — Official Data Source Research and Validation

**Phase:** 1.5 — Source research and validation (no schema design, no implementation)
**Research date:** 14 November 2026
**Status:** Research complete. Phase 2 implementation not started.

## How to read this document

Every claim below is tagged so we never confuse what is *verified* with what is *assumed*:

| Tag | Meaning |
|---|---|
| **[VERIFIED]** | Read directly from the official primary source (PDF or page) during this research. Section/page cited. |
| **[REPORTED]** | Stated by an official body in secondary material (news release, programme page), not in a numbered standard. |
| **[UNRESOLVED]** | Could not be confirmed from an official source, or official sources conflict. Must not be coded as logic. |

**Hard rule for the team:** only **[VERIFIED]** rows may become screening eligibility logic in code. Anything **[REPORTED]** or **[UNRESOLVED]** must be surfaced as a configurable parameter with a visible "unverified" flag, never hard-coded as clinical truth.

---

## 1. Executive summary of findings

Three findings changed the plan materially:

1. **The two MVP pathways are fully specified in official, citable DoH standards.** We found the governing documents for both — the IFHAS adult standard (V10, July 2025) and the Well-Child Visit standard (V10, December 2025). Both contain exact age groups, intervals, test components, referral windows and KPIs. **We do not need to invent any eligibility criteria.**
2. **DoH "Open Data" is not a downloadable dataset catalogue.** It is a set of embedded Power BI / Tableau **dashboards**. Downloadable Abu Dhabi health CSVs exist on a *different* portal (`addata.gov.ae`), which was unreachable from this network. Treat local population data as **aggregate context only**.
3. **Health data may not leave the UAE.** Federal Law No. 2 of 2019 plus ADHICS v2 restrict cross-border transfer of patient health data, and the DoH Responsible AI Standard requires AI compute/storage to sit inside the UAE. This conflicts with the repo's current GCP Cloud Run target and must be addressed in the architecture narrative.

A fourth, time-critical finding is in §9: the hackathon's stated working-prototype deadline is **20 November 2026**.

---

## 2. Source-by-source findings

### A. Abu Dhabi healthcare and government sources

---

#### Source 1 — Abu Dhabi DoH Open Data
**URL:** https://www.doh.gov.ae/resources/opendata

| Attribute | Finding |
|---|---|
| Publisher | Department of Health, Abu Dhabi (DoH) |
| What it provides | **[VERIFIED]** Page title is "Open Data **Dashboards**". Self-described as "the first-of-its-kind online portal that will relay the Emirate's most up-to-date health statistics in a visual and engaging manner" with "interactive filters" and international benchmark comparison. |
| Data type | **Aggregate statistics only.** No individual-level records. |
| Downloadable data | **[VERIFIED] No.** The page contains no dataset file links. It embeds `app.powerbi.com/view?r=...` and `tableau.doh.gov.ae/javascripts/api/viz_v1.js` — view-only visualisations rendered client-side. |
| API | **[VERIFIED] None published.** No API endpoint is advertised. *(Per the brief: we did not infer an API from the site's existence — we inspected the page source and found only BI-embed references.)* |
| Registration | Not required to view dashboards. An optional email "Subscribe for updates" field exists. |
| Licensing | **[UNRESOLVED]** No licence is stated on the dashboards page. |
| Update frequency | Page footer showed "Last updated: 13 Nov 2026". Per-dashboard refresh cadence is not stated. |
| Limitations | Not machine-readable; figures would have to be read off dashboards and transcribed by hand. Not suitable as a pipeline input. |

**Relevance to PulseReach:** Low as a data source, moderate as *context* for framing the problem (e.g. citing prevalence in the pitch narrative).

**Downloadable Abu Dhabi health data actually lives elsewhere — see Source 1b.**

---

#### Source 1b — Abu Dhabi Open Data Platform (follow-on discovery, not in the original nine)
**URL:** https://addata.gov.ae/group/department-health

| Attribute | Finding |
|---|---|
| Publisher | Abu Dhabi Government (hosts a DoH publisher group) |
| What it provides | **[REPORTED]** ~33 DoH datasets, including *Birth Statistics*, *Death Statistics*, *Blood Banks*, *Health Facilities by Sector*, and inpatient provider market structure. CSV resources. |
| Licensing | **[REPORTED]** Abu Dhabi Government Open Data License. |
| Accessibility from our environment | **[VERIFIED] Unreachable.** TLS handshake failed repeatedly (`SSL_ERROR_SYSCALL`) on both the portal and a probed CKAN API path, with and without certificate verification. Likely geo- or network-restricted. |
| Limitations | Aggregate only. Dataset currency looked dated where visible (e.g. a Birth Statistics resource last modified July 2022). |

> **Action:** a teammate on an Abu Dhabi / UAE network should confirm these datasets and their licence before we cite them as available. Listed as **[REPORTED]** until then. **Do not** cite specific dataset contents in the submission until verified.

---

#### Source 2 — IFHAS (Abu Dhabi Preventive Screening Programme)
**URL:** https://www.adphc.gov.ae/en/Public-Health-Programs/IFHAS
**Governing standard (key discovery):** *Standard for the Provision of the Periodic Comprehensive Screening Program for Adults – IFHAS*, Ref. **DoH/SD/ADPHC-CHS/IFHAS/V10/2025**, Version V10, published & effective **July 2025**, owner Community Health Sector – ADPHC, contact `IFHAS.Support@adphc.gov.ae`.
**Standard PDF:** https://www.doh.gov.ae/-/media/EE758C3B77314BC394F2479AEF803AA2.ashx

The public programme page alone was **not** sufficient — it gives no interval table. The numbered standard does, and it is the document our adult logic must cite.

| Attribute | Finding |
|---|---|
| Publisher | DoH / Abu Dhabi Public Health Center (ADPHC) |
| Content type | Clinical standard: eligibility, test components, frequency, referral pathway, KPIs. No datasets. |
| Downloadable | Yes — public PDF, no registration. |
| API | None. |
| Update frequency | **[VERIFIED]** Revision every 3 years and as needed; revision date July 2028. |
| Limitations | Specifies *what* should happen clinically; contains no population or patient data. |

**Eligibility — [VERIFIED], §4.5:**
- §4.5.1 Member of the **THIQA** program
- §4.5.2 **18 years old and above**
- §4.5.3 Female or male based on the specific screening programme eligibility criteria

> **[UNRESOLVED] — age ceiling.** §4.5.2 states "18 years old and above" with no upper bound, yet *every* package in Appendix 7 caps its target group at **75 years**. ADPHC news material (Feb 2024) says "aged between 18 to 75 years", while the current programme page says "18 and above". **Decision for the MVP:** treat 18+ as eligible for the *programme*, and apply each package's own age band as the operative rule — because the package bands are what Appendix 7 actually specifies. Flag the >75 cohort as out-of-scope-pending-clarification rather than silently excluding or including them.

**Adult screening matrix — [VERIFIED], Appendix 7 "Assessment Measures per Age Group":**

| Package | Target group | Frequency |
|---|---|---|
| Comprehensive Screening Major Package (M&F) | 18–39 years | Every 3 years |
| Comprehensive Screening Major Package (M&F) | 40–64 years | Every 3 years |
| Comprehensive Screening Major Package (M&F) | 65–75 years | Every 3 years |
| Minor Package — Vision Screening (M&F) | 40–75 years | Annually |
| Minor Package — Hearing & Dementia (M&F) | 50–64 years | Every 3 years |
| Minor Package — Hearing & Dementia (M&F) | 65–75 years | Annually |
| Oral Health Package (M&F) | 18–75 years | Annually |
| Cervical Cancer Screening (F) | 25–29 years | Every 3 years (Pap smear) |
| Cervical Cancer Screening (F) | 30–65 years | Every 5 years (**HPV test ONLY**) |
| Breast Cancer — Clinical Breast Exam (F) | 20–34 years | Every 3 years |
| Breast Cancer — CBE + Gail Model risk assessment (F) | 35–39 years | Every 3 years |
| Mammography (F) | 40–75 years | Every 2 years |
| Female Reproductive Health Screening | 20–35 years | Every 3 years |
| Male Reproductive Health Screening | 20–35 years | Every 3 years |
| Fecal Immunochemical Test — FIT (M&F) | 40–75 years | Annually |
| Liquid Biopsy / Shield test (M&F) | 40–75 years, review criteria | Every 3 years |
| Colon Cancer Screening — colonoscopy (M&F) | 40–75 years | Every 10 years |
| DEXA scan (M&F) | 60–75 years | Every 2 years |
| Lung Cancer Screening — low-dose CT (M&F) | 55–75 years, **high risk only** | Annually |
| Abdominal Aortic Aneurysm — ultrasound (M) | 65–75 years, **ever smoked** | **Once in a lifetime** |

**Major Package components — [VERIFIED], Appendix 7** (identical across 18–39, 40–64, 65–75): IFHAS Health Questionnaire; Weight; Height; BMI; Waist circumference / waist-hip ratio; Blood Pressure; Consultation; PHQ-9 depression screening; GAD-7 anxiety screening; Physical exam; Blood collection; Random Blood Sugar; HbA1c; Lipid Panel; S. Creatinine; CBC.

**Lung cancer high-risk criteria — [VERIFIED], Appendix 7 footnote:**
- 30 pack-year smoking history, and/or tobacco cessation <15 years; **or**
- 20 pack-year tobacco use, and/or cessation <15 years **plus one additional risk factor**; **or**
- 20-year history of water pipe (Shisha) and/or Dokha, Medwakh, or other smoked tobacco.

**Liquid biopsy criteria — [VERIFIED], Appendix 7:** *Inclusion* — unwilling to have colonoscopy or FIT. *Exclusion* — personal history of colorectal cancer; known hereditary/germline CRC risk (e.g. Lynch syndrome, FAP); inflammatory bowel disease diagnosis.

**Workflow timings — [VERIFIED]** (these are the outreach/completion rules PulseReach actually models):
- §4.7.1 Providers must operate an **"Invitation System"** for first screening, rescreening, and **recall for positive and insufficient results**.
- §4.9.2.1 Results communicated to participant **within 10 days** of the initial visit.
- §4.11.4.3 Participant journey completed and results reported via Shafafiya **within 15 days** of the initial visit; **if the IFHAS package is not completed, claims cannot be submitted**.
- §4.11.4.4 KPIs reported within **21 days** after each quarter ends.
- Appendix 9 note: referrals for abnormal findings within **15 working days** of releasing results.
- §4.11.4.1 Participant is **tagged for IFHAS** to allow tracking through **Malaffi**, with results tagged in **Sahatna**.

**Quality indicators — [VERIFIED], Appendix 9:** Participation Rate per package (target **>85%**); Abnormal Findings Rate per package; Referral of participants with abnormal findings (target stated as **>100%** — evidently a typo for 100%, flagged rather than reproduced as logic).

**Referral pathway — [VERIFIED], Appendix 8:** maps each abnormal test to a specialist (e.g. PHQ-9/GAD-7 → Psychiatrist, Psychologist, or Family Physician with Mental Health privilege; FIT/colonoscopy/Shield → Gastroenterologist; HbA1c/RBS → GP, Family Physician, Internal Medicine, Endocrinologist; AAA ultrasound → Vascular Surgeon).

**2025 programme expansion — [UNRESOLVED]:** secondary sources report an expansion adding reproductive health screening, mental health, and non-invasive colorectal tests. The reproductive-health (20–35) and CBE (20–34 / 35–39) bands *are* in the V10 standard and are therefore **[VERIFIED]** above; specific press-reported age bands that do not appear in the standard are not adopted.

---

#### Source 3 — Abu Dhabi Well-Child Visit Standard (2025)
**URL:** https://www.doh.gov.ae/-/media/Feature/Resources/Standards/2025/Well-Child-Visit-Standard.ashx
**Document:** *Standard for Well-Child Visits*, Ref. **DOH/WCV/SD/10/2025**, Version V10, **Revised**, published **December 2025**, **Effective Date: TBD**, owner Community Health Sector – ADPHC, contact `WCV.Support@adphc.gov.ae`. 32 pages.

> **[VERIFIED] Caveat that matters:** the standard's own **Effective Date is "TBD"**. We should describe it as the current published standard, not as an in-force regulation.

| Attribute | Finding |
|---|---|
| Publisher | DoH / ADPHC |
| Scope | **[VERIFIED]** §1.1 — children **aged 1 month to 6 years**. §1.2 applies to all licensed facilities providing WCV screening in Abu Dhabi. |
| Content type | Clinical standard. No datasets. |
| Downloadable / API | Public PDF, no registration. No API. |
| Update frequency | **[VERIFIED]** Revision period 3 years; revision date December 2029. |
| Limitations | Newborns follow the separate Newborn Screening Standard (§3.2.7). Immunisation detail is delegated to EPI circular No. 39/2024. |

**Visit schedule — [VERIFIED], §3.2.3 and Appendix 1.** Fourteen visits:

**1 month · 2 months · 4 months · 6 months · 9 months · 12 months · 15 months · 18 months · 2 years · 2.5 years · 3 years · 4 years · 5 years · 6 years**

Age-band definitions — **[VERIFIED]** §3.2.5–3.2.7: Infancy = 1–11 months; Early childhood = 1–4 years; Middle childhood = 5–6 years.

**Screening requirements by age — [VERIFIED], §3.3–3.8 and Appendix 1:**

| Screening | Ages performed | Source section |
|---|---|---|
| Growth: weight + head circumference, Z-scores (WHO standards) | Every visit, 1 month → 6 years; head circumference measured routinely **up to 2 years** | Appendix 1; §3.8.1.5 |
| Height/BMI-for-age (replaces weight-for-length) | From 2 years onward | Appendix 1 |
| Physical examination + vital signs | Every visit | §3.2.1 |
| Developmental milestones (4 domains) | Every visit | §3.8.5, Appendix 6 |
| Vision / eye screening | Every visit, age-specific battery | §3.4, Appendix 1 |
| Hearing screening | At birth (newborn standard); **1 or 2 months if not done at birth**; then **4, 5 and 6 years** (Pure Tone Audiometry) | §3.3.4, Appendix 1 |
| DDH — Ortolani & Barlow maneuvers | 1, 2, 4 months | §3.5.4 |
| DDH — limited abduction / limb shortening / asymmetric thigh folds | 6, 9, 12 months until walking | §3.5.5 |
| Anemia — CBC | **12 months**; (15 or 18 months if not done at 12, or if risk factors) | §3.6.1, Appendix 1 |
| Oral/dental screening by dentist or hygienist | **12, 18, 24 months, 2.5, 3, 4, 5, 6 years** | §3.7.5 |
| Blood pressure | **3, 4, 5, 6 years** (under 3 only with specific risk conditions) | §3.8.3.1–3.8.3.2 |
| Autism screening — M-CHAT-R | **18 months and 24 months** | §3.8.4.1 |
| Developmental delay — IDAQ (6 questions) | **18 months** (ASQ-3/ASQ-4 to follow upon DoH-ADPHC circular) | §3.8.4.2 |
| Critical Congenital Heart Disease | Verify newborn screening result is in the record | §3.8.6.2 |
| Vitamin D counselling | 1–12 months: 400 IU/day; 12 months–6 years: 600 IU/day | §3.8.2 |

**Follow-up and referral windows — [VERIFIED], §3.9.1:**
- §3.9.1.3 Initial follow-up referral **must be initiated within 7 days** of screening results.
- §3.9.1.4 Specialist evaluation or diagnostic testing scheduled **within 2–4 weeks** depending on severity/urgency.
- §3.9.1.1 Screening offered at flexible hours including evenings and weekends.

**M-CHAT-R scoring and referral — [VERIFIED], Appendix 5.1:**

| Score | Action |
|---|---|
| 0–2 (low risk) | If screened at 18 months, **re-screen at 24 months**. If done at 24 months, no further screening unless indicated. |
| 3–7 (moderate risk) | Refer to child neurodevelopment clinic **within 4 weeks**; refer to speech therapy **within 4 weeks**; PHC follow-up after 1 month to confirm referral succeeded. |
| 8+ (high risk) | Refer to child neurodevelopment clinic **within 2 weeks**; speech therapy **within 2 weeks**; PHC follow-up after 1 month. |

**IDAQ referral rule — [VERIFIED], §3.8.4.2:** if question 1 is answered **YES**, or any of the other 5 questions is answered **NO**, refer to a pediatric neurologist or neurodevelopment clinic.

**Anemia threshold — [VERIFIED], §3.6.3:** hemoglobin **<11 g/dL for children <6 years** requires further evaluation of etiology.

**KPIs — [VERIFIED], §5.1:** uptake rate by age group across 1, 2, 4, 6, 9, 12, 15, 18, 24 months and 3, 4, 5, 6 years; CBC uptake at 12/15/18 months; M-CHAT-R uptake at 18 and 24 months (**target 100%**); abnormal M-CHAT-R referred (**target 100%**); IDAQ uptake at 18 months (**target 100%**); IDAQ abnormal cases referred (**target 100%**).

**Coverage/payment — [VERIFIED], §3.10.1:** UAE Nationals covered under **Thiqa** preventive care. Non-Nationals (Basic/Enhanced) per policy schedule of benefits; Government Mandated Funds limited to **screening only**, excluding intervention and supplements. §3.10.1.3 a child attending as a **defaulter (catch-up vaccine visit)** within the WCV schedule remains eligible for screening/testing for that age group — directly relevant to our "overdue" logic.

**Parental refusal — [VERIFIED], §4.2.1:** refusal must be documented in the medical record with signature. PulseReach must model refusal as a distinct state, not as "not yet done".

---

#### Source 4 — Abu Dhabi Responsible AI Standard (2025)
**URL:** https://www.doh.gov.ae/-/media/Feature/Resources/Standards/2025/Responsible-AI-Standard-V1.ashx
**Document:** *Responsible Artificial Intelligence (AI) Standard*, Ref. **DoH/ST/DDGO/RAI/V1/2025**, V1, **New**, published & effective **October 2025**, owner Data and Digital Governance Office (DDGO), contact `DDG@doh.gov.ae`. 15 pages. Revision period: one year.

**Applicability — [VERIFIED] §1.2:** applies to DoH and **all licensed healthcare entities** in Abu Dhabi engaged in "the development, procurement, or deployment" of AI systems — including systems "developed internally, sourced from third-party vendors, or created through research collaborations", covering "the entire lifecycle from inception and deployment to decommissioning."

Structure — §1.3: (1) Core Foundations, (2) Data Management for AI, (3) AI Risk Management, (4) AI Literacy.

**Requirements most binding on PulseReach — [VERIFIED]:**

| Req. | Requirement | Implication for PulseReach |
|---|---|---|
| §3.1.1.2 | Human-in-the-loop or human-on-the-loop oversight; **clear escalation protocols** by risk level | Risk flags must route to a clinician, never auto-contact a patient on model output alone |
| §3.1.4.5.1 | **Compute and storage — active *and* disaster recovery — must be situated within the UAE**; remote access for dev/support teams exclusively from within the UAE | **Directly conflicts with the repo's stated GCP Cloud Run target.** Must be addressed. |
| §3.1.4.4.2 | **"Production data shall not be used to train the model."** | Reinforces synthetic-only training for the MVP |
| §3.1.4.4.1 | Privacy-by-design; minimum necessary data; purpose-specific, aligned to informed consent (ADHICS, PDPL) | Field-level minimisation in the data model |
| §3.1.4.4.3 | Anonymisation, differential privacy, secure multi-party computation, federated learning to be incorporated | Aspirational for MVP; name honestly as not implemented |
| §3.1.5.1.1–3 | Training/validation/test datasets must reflect target population diversity; **data representativeness audits**; traceable bias mitigation | **NHANES-trained logic on an Abu Dhabi population directly implicates this.** See §5. |
| §3.1.6.1.1 | Must inform patients/clinicians when AI contributes to decisions, with function, limitations, intended outcomes | Explicit AI disclosure in the UI |
| §3.1.6.1.3 | Patients must be informed of their **right to opt out** of AI-driven services; clear consent mechanisms | Opt-out must be a first-class state in outreach |
| §3.1.6.2.1–3 | Document data provenance, preprocessing, known limitations; **end-to-end traceability logs** of inputs, outputs, version history | Prediction audit log |
| §3.1.6.3.1–3 | **Role-specific explanations**: clinician-facing = diagnostic rationale, confidence, next steps; patient-facing = plain language | Two explanation renderings, not one |
| §3.1.7.2.2 | **Clinicians retain ultimate decision-making authority** in all AI-assisted scenarios | "Recommend", never "decide" |
| §3.1.7.2.3 | **Override mechanisms and audit trails** embedded | Clinician override must be recorded |
| §3.2.1.3 | Every dataset mapped to a clearly defined AI task; **no speculative or indefinite-purpose collection** | Justify each field in the dictionary |
| §3.2.1.5 | **Open Data licences must be reviewed by Legal Affairs** for usage/commercial restrictions | Applies to our NHANES and Abu Dhabi open-data use |
| §3.2.3.1 | Data must be clinically validated, statistically appropriate, representative, free of errors/biases | Synthetic data must be described as *unvalidated* |
| §3.2.4–3.2.5 | Dataset versioning (immutable, semantic versioning, change logs); **datasheets / data cards** | Version the synthetic generator and ship a data card |
| §3.3.1.2.2 | Residual risk tiers: **Very High = prohibited**; High = conformity assessment before and after deployment, coordinated with DDGO; Medium = governance + safeguards; Low = monitoring | A real deployment would need a formal risk classification |

---

#### Source 5 — ADHICS v2 Implementation Guideline
**URL:** https://www.doh.gov.ae/-/media/Feature/Resources/Guidelines/ADHICS-v2-implemetation-guideline.ashx
**Document:** *Guidelines for the Implementation of Abu Dhabi – Healthcare Information and Cyber Security*, Ref. **DOH/GL/ICSO/ADHICS/V2/2024**, V2, published **May 2024**, **effective August 2024**, owner DoH Information & Cyber Security Office. **286 pages.** Contact `ADHICS@doh.gov.ae`.

**Applicability — [VERIFIED]:** "Any entity including but not limited to, Healthcare Facility, Payer, Healthcare Technology and Service Provider in the Emirate of Abu Dhabi that generate, access, store, use, process and/or transmit health information." Scope explicitly includes third-party systems and ecosystem platforms — **Shafafiya, Malaffi, DoH e-Services**.

**Legal basis — [VERIFIED]:** Federal Law No. (2) of 2019 on ICT in health, and Federal Decree-Law No. (45) of 2021 on Data Privacy.

**[VERIFIED] Important framing:** the guideline states it "is only an implementation guideline and does not override ADHICS or any other regulatory documents" — in case of contradiction, the **Standard** governs. It also states that implementing ADHICS "does not exclude the entity from any legal liabilities." Control applicability is tiered by entity maturity/complexity/risk (Standard §A-2), so we cannot claim a tier for ourselves.

**Controls most relevant to PulseReach — [VERIFIED], Data Privacy Policy (§7):**

| Area | Requirement |
|---|---|
| **Data residency** | "will ensure that PII and PHI **or its backup in any form is not stored, processed or transferred outside UAE**, except in cases where a valid exemption to do so is issued by DoH" |
| Consent | **Explicit consent** before collection of PII/PHI, including the right to withdraw; records of consent kept to demonstrate compliance |
| Collection limitation | Data minimisation — limited and relevant PII/PHI relative to purpose |
| Use limitation | Not used for any purpose other than what was agreed at collection |
| Access rights | Data subject may review, correct, update, suppress or modify; **may object to processing and to decisions made by automated processing**; data provided in machine-readable format; routed via the Data Protection Officer |
| Retention & disposal | Retain only as long as needed for the stated purpose; where no longer needed, **anonymise using identity concealment** |
| Third-party disclosure | Only with explicit consent; risk evaluation, due diligence, and privacy provisions in the contract/SLA |
| Breach management | All privacy incidents reported to the ISM/DPO, recorded and tracked |
| Logging | Security event logging fully activated; log retention period set by asset value; **NTP to ensure accuracy of audit logs**; users restricted from changing system time |

**Security policy set — [VERIFIED]:** the guideline enumerates 21 required policies, including Healthcare Data Privacy, Access Control, Cloud Security, Third Party Security, Information Security Incident Management, Information Systems Continuity, and Compliance.

> **Note on "the right to object to automated processing"** — combined with the Responsible AI Standard's opt-out requirement (§3.1.6.1.3), this is a concrete product requirement, not boilerplate: PulseReach needs a per-patient flag that suppresses AI-driven risk scoring and outreach.

---

#### Source 6 — UAE Digital Economy / health data context
**URL:** https://www.trade.gov/country-commercial-guides/united-arab-emirates-digital-economy
**Publisher:** U.S. International Trade Administration (ITA), U.S. Department of Commerce. **Last published 20 September 2024.**

This is a **foreign-government commercial guide, not a UAE legal source.** Use for orientation only; cite UAE instruments directly for any compliance claim.

**[REPORTED] findings:**
- **Federal Decree-Law No. 45 of 2021 (PDPL)** took effect January 2022, applies to data subjects residing or doing business in the UAE, and — importantly — **excludes health data, which falls under separate law**. As of September 2024 implementing regulations had not been published.
- **Federal Law No. 2 of 2019 (Health Data Law)** generally **restricts transferring patient health data outside the UAE**; ten exemptions exist under Ministerial Resolution 51 of 2021, but the guide states the process for obtaining them is "not clear."
- **ADHICS v2** permits cloud use and names AWS, Microsoft Azure and SaaS providers for storing health data **inside** the UAE, but **blocks cross-border health data flows including for backup**, absent a regulator exemption.
- Localisation requirements apply to **health and government data**.
- UAE AI Strategy 2031; Microsoft, Oracle and AWS operate UAE cloud regions.

**Relevance:** this is the clearest plain-language confirmation that our hosting choice is a compliance decision, not just an engineering one.

---

### B. Public datasets

---

#### Source 7 — CDC NHANES
**URL:** https://wwwn.cdc.gov/nchs/nhanes/

| Attribute | Finding |
|---|---|
| Publisher | CDC / National Center for Health Statistics (NCHS) |
| Content type | **Individual-level, de-identified research survey data** (complex multistage probability sample of the US population) |
| Components | **[VERIFIED]** Demographics, Dietary, Examination, Laboratory, Questionnaire, plus Limited Access Data |
| Cycles | Continuous NHANES from 1999–2000 onward. Most recent cycle with published data components: **August 2021 – August 2023**. A 2025–2027 cycle is listed with documentation only. |
| Format | **[VERIFIED] SAS XPT transport files.** Confirmed by byte-range request on `DEMO_L.xpt` → file begins `HEADER RECORD*******LIBRARY HEADER RECORD!!!!!!!...SAS` |
| Downloadable | **[VERIFIED] Yes — directly, no registration, no login.** Verified HTTP 206 partial content on a public URL. |
| API | **[VERIFIED] None.** Files are served as static downloads; there is a "Search Variables" browse tool, but no data API. |
| Licensing | **[REPORTED]** US federal government work, conventionally public domain; NCHS publishes a Data User Agreement. **[UNRESOLVED]** — exact DUA terms were not read in full. Per RAI §3.2.1.5, Legal review would be required before any commercial use. |
| Update frequency | Released by 2-year cycle, with periodic appended files |

**Verified file URL pattern** (case-sensitive):
`https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/<FILE>_L.xpt`

Useful files for the adult pathway (the `_L` suffix denotes the Aug 2021–Aug 2023 cycle):

| File | Component | Why it matters for PulseReach |
|---|---|---|
| `DEMO_L.xpt` | Demographics | Age, gender, education, income ratio, survey weights |
| `BMX_L.xpt` | Examination — body measures | Height, weight, BMI, **waist circumference** |
| `BPXO_L.xpt` | Examination — oscillometric BP | **Blood pressure** |
| `GHB_L.xpt` | Laboratory | **HbA1c** |
| `GLU_L.xpt` | Laboratory | Fasting glucose |
| `TCHOL_L.xpt` | Laboratory | Total cholesterol |
| `DIQ_L.xpt` | Questionnaire | Diabetes status |

These map almost one-to-one onto the IFHAS Major Package biochemical/physical measures (BMI, waist, BP, HbA1c, random blood sugar, lipids) — which is precisely why NHANES is useful for *pipeline and model mechanics*.

**Limitations — stated plainly, as the brief requires:**
> NHANES is a **United States** survey. It **cannot** establish Abu Dhabi prevalence, cannot validate local clinical thresholds, and cannot be presented as evidence about the Abu Dhabi population. The UAE differs materially in age structure, nationality mix, diabetes prevalence and consanguinity patterns. Under Responsible AI Standard §3.1.5.1.1, training data must reflect the diversity of the **target** population — so any NHANES-derived model is a **technical scaffold only**, and must be labelled as such in the UI and the submission. It also contains **no** well-child, IFHAS, outreach or appointment constructs.

---

#### Source 8 — Synthea
**URL:** https://synthetichealth.github.io/synthea/

| Attribute | Finding |
|---|---|
| Publisher | **The MITRE Corporation** (not-for-profit) |
| Content type | **Synthetic individual patient records** — "realistic but not real" |
| Licence | **[VERIFIED] Apache License 2.0** (fetched `LICENSE` from the repository) |
| Output formats | **[VERIFIED]** HL7 **FHIR R4, STU3, DSTU2**; **C-CDA**; **CSV** |
| Downloadable | Yes — generator source plus pre-built sample datasets (1,000+ synthetic patients) |
| API | No service API; it is a **local generator** (run it yourself) |
| Registration | None |
| Limitations | Module coverage is US-centric; care patterns, payers and demographics model the US |

**[VERIFIED] Module gallery (37 modules):** Allergic Rhinitis, Allergies, Appendicitis, Asthma, Atopy, Attention Deficit Disorder, Bronchitis, Colorectal Cancer, Contraceptives, Contraceptive Maintenance, COPD, Dementia, Dermatitis, Ear Infections, Epilepsy, Female Reproduction, Fibromyalgia, Food Allergies, Gout, Homelessness, Injuries, Lung Cancer, Lupus, Med Rec, Metabolic Syndrome Care, Metabolic Syndrome Disease, Opioid Addiction, Osteoarthritis, Osteoporosis, Pregnancy, Rheumatoid Arthritis, Self Harm, Sexual Activity, Sinusitis, Sore Throat, Total Joint Replacement, Urinary Tract Infections, **Wellness Encounters**.

**What Synthea gives PulseReach:** patients with demographics; longitudinal **encounters**; **conditions**; **observations** (vitals and labs — the HbA1c / BP / BMI / lipid shapes we need); **medications**; **care plans**; and FHIR-compatible output. The `Metabolic Syndrome Disease` / `Metabolic Syndrome Care` modules, plus `Colorectal Cancer`, `Lung Cancer`, `Osteoporosis` and `Dementia`, align loosely with IFHAS target conditions.

**What Synthea does NOT give us — [VERIFIED] by module inspection:**
- **No Abu Dhabi Well-Child Visit schedule.** There is no well-child or pediatric-preventive module. `Wellness Encounters` produces generic wellness visits on a US cadence, not the 14-visit 1-month→6-year DoH schedule.
- **No IFHAS screening records** (no package concept, no 3-year periodicity, no Thiqa eligibility).
- **No outreach events, invitations, reminders, or opt-outs.**
- **No appointment bookings.**
- **No screening-completion or defaulter/recall state.**
- **No M-CHAT-R / IDAQ / PHQ-9 / GAD-7 instrument results** as structured scored assessments.
- No Thiqa/Daman payer model, no Emirates ID, no Abu Dhabi region (Abu Dhabi City / Al Ain / Al Dhafra).

**Conclusion:** Synthea is the right **base population generator**; the Abu Dhabi preventive-care layer must be generated by us (see §6).

---

### C. Official hackathon reference

---

#### Source 9 — Future Health Digital Innovation Challenge
**URL:** https://hack2skill.com/event/futurehealthchallenge/

| Attribute | Finding |
|---|---|
| Organiser | Future Health — A Global Initiative by Abu Dhabi, via Hack2skill. Co-creators: **Microsoft, Inception (G42), MBZUAI** |
| Focus areas | **Fertility**, **Population Health**, **Wellbeing** — 10 challenge statements |
| Eligibility | Worldwide; individuals and teams **up to 5 members**; team lead 18+; technology-neutral, hardware welcome |
| Submission | **Working prototype**, plus technical documentation, assumptions and limitations |
| Prizes | **[REPORTED]** USD 105,000 total (50k / 35k / 20k) |
| Evaluation criteria | Health impact; technical depth; working solution & demo quality; **responsible AI and data governance**; scalability; commercial viability |

**Dates — [VERIFIED from the event page], with a [UNRESOLVED] conflict:**
- Registration: 15 Oct – 10 Nov 2026
- **Working prototypes due: 20 Nov 2026**
- Evaluation: 20–30 Nov 2026
- Awards at GITEX: 7–11 Dec 2026

> **[UNRESOLVED]** Secondary listings (a Business Wire release and an aggregator) give **15 November 2026** as the application deadline instead of 10 November. The page itself notes dates may change. **Today is 14 November 2026** — so under either reading, registration has closed or closes imminently, and the prototype deadline is **~6 days away**. Confirm standing with the organisers before further build investment.

**Data/build rules — [VERIFIED]:** solutions must include safe triage with clinical boundaries and **human oversight**, must be demonstrable safely, and (per the reproductive-health statement) require explicit consent, data minimisation, user-controlled sharing, strong access controls and clear explanation of data use. Full terms are in the Challenge Rules.

**Direct relevance:** "Population Health" is PulseReach's category, and **"responsible AI and data governance" is an explicit scoring criterion** — which makes §5 of this document a scored asset, not overhead.

---

## 3. Source-to-requirement mapping

| PulseReach Requirement | Official Source | Relevant Information | Availability | MVP Usage |
|---|---|---|---|---|
| **Adult screening eligibility & intervals** | IFHAS Standard DoH/SD/ADPHC-CHS/IFHAS/V10/2025 (§4.5, App. 6–7) | Thiqa + 18 years and above; 20 packages with exact age bands and frequencies; Major Package test components | Public PDF | **Primary rule source.** Encode Appendix 7 verbatim as the eligibility/due-date rule table |
| **Adult referral & completion workflow** | Same (§4.7, §4.9, §4.11, App. 8–9) | Invitation System; results in 10 days; reporting in 15 days; referral within 15 working days; participation target >85% | Public PDF | Drives outreach states, due/overdue windows, and the dashboard KPIs |
| **Child Well-Child Visits** | WCV Standard DOH/WCV/SD/10/2025 (§3.2.3, App. 1) | 14 visits, 1 month → 6 years; per-age screening battery | Public PDF (Effective Date TBD) | **Primary rule source.** Encode the 14-visit schedule and per-age requirements |
| **Child developmental screening logic** | WCV Standard §3.8.4, App. 5.1–5.2 | M-CHAT-R at 18 & 24 months with 0–2 / 3–7 / 8+ referral tiers; IDAQ at 18 months | Public PDF | Risk-flag + referral-urgency logic for the child pathway |
| **Child follow-up windows** | WCV Standard §3.9.1.3–4 | Referral initiated within 7 days; specialist within 2–4 weeks | Public PDF | Overdue/escalation timers |
| **Patient demographics** | Synthea; IFHAS App. 1 questionnaire | Synthea: age, gender, address. IFHAS: DOB, Emirates ID, gender, place of residence (Abu Dhabi City / Al Ain / Al Dhafra), education, employment | Apache 2.0 generator + public PDF | Synthea base + custom Abu Dhabi fields per the IFHAS questionnaire |
| **Clinical measurements** | NHANES (`BMX_L`, `BPXO_L`, `GHB_L`, `GLU_L`, `TCHOL_L`); Synthea observations | BMI, waist circumference, BP, HbA1c, glucose, lipids | Public XPT; local generator | NHANES for realistic value **distributions** and pipeline testing; Synthea for per-patient records |
| **Screening history** | — | No source provides Abu Dhabi screening histories | **Not available** | **Custom synthetic generation** (see §6) |
| **Population indicators** | DoH Open Data Dashboards; addata.gov.ae; SCAD | Aggregate statistics only | View-only dashboards; portal unreachable from here | **Context/narrative only.** Never joined to patient records |
| **AI governance** | Responsible AI Standard DoH/ST/DDGO/RAI/V1/2025 | Human oversight, UAE residency, explainability, bias audits, opt-out, traceability, risk tiers | Public PDF | Design constraints + the governance section of the submission |
| **Security requirements** | ADHICS v2 DOH/GL/ICSO/ADHICS/V2/2024 | PHI must not leave the UAE; consent; minimisation; retention/anonymisation; audit logging; automated-processing objection | Public PDF (286 pp) | Access control, audit log, retention design |
| **Synthetic patient records** | Synthea (MITRE) | FHIR R4 / C-CDA / CSV; 37 modules; encounters, conditions, observations, medications, care plans | Apache 2.0 | Base population generator |

---

## 4. Recommended downloads (minimal set)

Deliberately minimal, per the brief. **Nothing restricted. No patient records.**

### Category 1 — Clinical guideline documents (download: YES — these are our rule sources)

| Item | URL | Format | Relevant content | Use | Licence/access | Download needed? |
|---|---|---|---|---|---|---|
| Standard for the Provision of the Periodic Comprehensive Screening Program for Adults – IFHAS (V10, Jul 2025) | https://www.doh.gov.ae/-/media/EE758C3B77314BC394F2479AEF803AA2.ashx | PDF, 24 pp | §4.5 eligibility; App. 6–7 tests & frequency; App. 8 referrals; App. 9 KPIs | Encode adult eligibility/interval rules | Public, no registration | **Yes** — cite section numbers in code comments |
| Standard for Well-Child Visits (V10, Dec 2025) | https://www.doh.gov.ae/-/media/Feature/Resources/Standards/2025/Well-Child-Visit-Standard.ashx | PDF, 32 pp | §3.2.3 + App. 1 schedule; App. 5 M-CHAT-R/IDAQ; §3.9.1 follow-up | Encode child visit schedule and referral logic | Public, no registration | **Yes** |
| Responsible AI Standard (V1, Oct 2025) | https://www.doh.gov.ae/-/media/Feature/Resources/Standards/2025/Responsible-AI-Standard-V1.ashx | PDF, 15 pp | Core foundations, data management, risk tiers | Governance design + submission section | Public | **Yes** — short and directly scored |
| Cervical Cancer Screening Standard (2025) | https://www.doh.gov.ae/-/media/Feature/Resources/Standards/2025/for-publication_-Standard-Cervical-Cancer-Screening-Standard.ashx | PDF, 14 pp | §3.1.2 women 25–65; HPV DNA every 5 years; §3.2.2.2 exit criteria; §3.3.1 targeted invitation | Cross-check cervical rules; invitation model | Public | Optional — reference only |

### Category 2 — Public aggregate datasets (download: NO)

| Item | URL | Why not |
|---|---|---|
| DoH Open Data Dashboards | https://www.doh.gov.ae/resources/opendata | **Reference only.** No downloadable files; Power BI/Tableau embeds. Cite figures in narrative if needed. |
| Abu Dhabi Open Data Platform — DoH group | https://addata.gov.ae/group/department-health | **Blocked from this network.** Aggregate CSVs only; would not feed patient-level logic. Verify from a UAE network before citing. |

### Category 3 — Public individual-level research datasets (download: YES, narrowly)

| Item | URL | Format | Fields | Use | Licence/access | Download needed? |
|---|---|---|---|---|---|---|
| NHANES Aug 2021–Aug 2023: `DEMO_L`, `BMX_L`, `BPXO_L`, `GHB_L`, `TCHOL_L` | `https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2021/DataFiles/<FILE>.xpt` | SAS XPT | Age, gender; BMI, waist; BP; HbA1c; total cholesterol | Realistic value distributions; pipeline/ML smoke-testing | Public domain (reported); NCHS DUA; no registration | **Yes — these 5 files only.** Not the full cycle. |

> Do **not** download dietary, limited-access, or the full laboratory set. We need distributions, not a research corpus.

### Category 4 — Synthetic datasets (download: YES)

| Item | URL | Format | Use | Licence | Download needed? |
|---|---|---|---|---|---|
| Synthea generator | https://github.com/synthetichealth/synthea | Java (runnable JAR) | Generate base synthetic population locally, with our own seed/size | **Apache 2.0** | **Yes** — generator, so we control volume and reproducibility |
| Synthea sample datasets (1k+ patients, FHIR R4 / CSV) | https://synthetichealth.github.io/synthea/ | ZIP (FHIR/CSV) | Fast start before the generator is wired up | Apache 2.0 | Optional — convenient for day 1 |

### Category 5 — Restricted healthcare records (download: **NO — EXCLUDED**)

| Item | Status |
|---|---|
| **Malaffi** (Abu Dhabi HIE) | **Not accessed.** Requires DoH/provider authorisation. Referenced in IFHAS §4.11.4.1 as the production tracking path. |
| **Shafafiya** (claims/e-claims) | **Not accessed.** Authorised providers only. |
| **Sahatna** (patient app) | **Not accessed.** |
| NHANES **Limited Access Data** | **Not requested.** Requires NCHS RDC application. |
| Any real patient record | **Excluded from the MVP entirely.** |

> No attempt was made to access any restricted system. All nine mandated sources were researched using public documents only.

---

## 5. PulseReach data strategy

### Role of each source

| Layer | Source | Role | Explicitly NOT used for |
|---|---|---|---|
| **Clinical rules** | DoH IFHAS V10/2025 + WCV V10/2025 standards | The *only* source of approved eligibility, intervals, and preventive-care logic | Not a data source |
| **Local population context** | DoH dashboards, addata.gov.ae, SCAD | Aggregate framing for the narrative ("why this matters in Abu Dhabi") | **Never** joined to patient records; never treated as individual data |
| **Technical reference data** | CDC NHANES | Realistic measurement distributions; pipeline and model smoke-testing | **Never** Abu Dhabi prevalence; never local clinical validation |
| **Synthetic individuals** | Synthea (Apache 2.0) | Base population: demographics, encounters, conditions, observations, medications, care plans | Not Abu Dhabi care pathways |
| **Custom synthetic layer** | PulseReach generator (to build) | IFHAS packages, WCV visits, outreach, appointments, completion, follow-up | Not clinically validated — must be labelled |
| **Real patient data** | Malaffi / Shafafiya / provider EMR | **Excluded** unless formally authorised | Out of scope for the hackathon MVP |

### Pipeline (how these eventually feed together)

```
  DoH Standards (PDF)                    Synthea (Apache 2.0)        NHANES (XPT)
  IFHAS V10 · WCV V10                    base population             value distributions
         │                                      │                           │
         ▼                                      ▼                           ▼
  rules/ as versioned config          data/synthetic/synthea/          calibration only
  (age bands, intervals,                      │                     (never per-patient)
   test components, referral                  │
   windows) — each entry                      ▼
   citing its section              PulseReach custom generator
         │                    (+ IFHAS packages, WCV visits, outreach,
         │                     appointments, completion, follow-up,
         │                     Thiqa eligibility, Emirates ID, region)
         │                                    │
         └──────────────┬─────────────────────┘
                        ▼
            data-pipeline/  validate → transform
                        │
                        ▼
      eligibility & due-date engine (rules, not ML)
                        │
                        ▼
         risk / prioritisation model (ML, explainable)
                        │
                        ▼
      backend API  →  frontend  →  clinician review  →  outreach
                        │
                        └──→ audit log (inputs, outputs, version, override)
```

**Design consequence worth stating now:** eligibility and "overdue" status are **deterministic rules** read from the DoH standards — not model output. The ML layer only *prioritises* among already-eligible people. This keeps us inside Responsible AI §3.1.7.2.2 (clinicians retain decision authority) and makes every flag explainable by citing a standard.

---

## 6. Records requiring custom synthetic generation

Neither Synthea nor NHANES provides these. All must be generated by us, and all must be labelled synthetic and clinically unvalidated.

| Record type | Why custom | Shape it must take (from the standards) |
|---|---|---|
| **IFHAS screening records** | No source models Abu Dhabi packages | Package name, target age band, frequency, completion date, per-test results — per IFHAS App. 6–7 |
| **Well-Child Visit events** | No pediatric preventive module exists | One event per age point across the 14 visits; per-age battery per WCV App. 1 |
| **Scored instruments** | Not structured in Synthea | M-CHAT-R (0–2 / 3–7 / 8+), IDAQ (6 items), PHQ-9, GAD-7 |
| **Outreach events** | Absent everywhere | Invitation, reminder, recall for positive/insufficient results (IFHAS §4.7.1); channel; **opt-out** (RAI §3.1.6.1.3) |
| **Appointment bookings** | Absent | Scheduled/attended/no-show; flexible hours incl. evenings/weekends (WCV §3.9.1.1) |
| **Screening completion** | Absent | Complete vs partial — note IFHAS §4.11.4.3: incomplete package ⇒ claims cannot be submitted |
| **Follow-up / referral events** | Absent | Adult: results in 10 days, referral within 15 working days. Child: referral within 7 days, specialist in 2–4 weeks |
| **Defaulter / catch-up state** | Absent | WCV §3.10.1.3 catch-up visits remain screening-eligible |
| **Refusal state** | Absent | WCV §4.2.1 documented parental refusal — distinct from "not yet done" |
| **Thiqa eligibility & local identifiers** | Absent | Thiqa membership (IFHAS §4.5.1), Emirates ID, region: Abu Dhabi City / Al Ain / Al Dhafra (IFHAS App. 1) |

---

## 7. Governance requirements needing formal review before real deployment

**We are not compliant, and this document does not claim otherwise.** Following selected recommendations is not compliance. Each item below needs formal review by a qualified party before any deployment with real data:

1. **AI risk classification and conformity assessment** — RAI §3.3.1.2.2. A preventive-care targeting system influencing clinical outreach is plausibly High Risk, requiring conformity assessment **before and after** deployment, coordinated with DoH DDGO. **Unassessed.**
2. **UAE data residency** — RAI §3.1.4.5.1 (compute/storage incl. DR inside the UAE; remote access only from within the UAE) and ADHICS (PHI and backups not stored/processed/transferred outside the UAE). **The repo currently targets GCP Cloud Run; region and residency are unresolved.**
3. **ADHICS control tier** — applicability depends on entity maturity/complexity/risk per Standard §A-2. **We cannot self-assign a tier.**
4. **Consent architecture** — ADHICS requires explicit consent with withdrawal rights and retained consent records; RAI requires AI opt-out. **Designed for synthetic data only; no real consent flow exists.**
5. **DoH licensing** — both clinical standards apply to *DoH licensed* providers. PulseReach is not a licensed entity; it would have to operate with/through one.
6. **Clinical validation** — RAI §3.2.3.1 requires clinically validated, representative data. Synthetic + US survey data satisfies neither. **No clinical validation has occurred.**
7. **Bias and representativeness audit** — RAI §3.1.5.1.1–2 requires datasets reflecting the target population and periodic representativeness audits. **NHANES-based work is US-population-derived; this gap must be stated in the submission.**
8. **Legal review of open-data licences** — RAI §3.2.1.5 requires Legal Affairs review of Open Data licences for usage/commercial restrictions. **Not performed** (applies to NHANES and Abu Dhabi open data).
9. **Data Protection Officer functions** — ADHICS routes subject access, correction, and objection-to-automated-processing requests through a DPO. **No DPO exists for this project.**
10. **Audit logging and retention** — ADHICS requires activated security event logging, asset-based log retention, NTP-synchronised clocks; RAI §3.1.6.2.3 requires end-to-end traceability of inputs/outputs/versions. **Design intent only.**

---

## 8. Unresolved questions

| # | Question | Status | How to resolve |
|---|---|---|---|
| 1 | IFHAS upper age limit — "18 and above" (§4.5.2) vs every package capping at 75 (App. 7) vs "18 to 75" in ADPHC news | **[UNRESOLVED]** | Contact `IFHAS.Support@adphc.gov.ae`. MVP uses each package's own band and flags >75. |
| 2 | WCV standard's **Effective Date is "TBD"** | **[UNRESOLVED]** | Contact `WCV.Support@adphc.gov.ae`. Describe as "published standard", not "in force". |
| 3 | Hackathon deadline: 10 Nov vs 15 Nov registration; prototype 20 Nov 2026 | **[UNRESOLVED]** | Confirm with organisers — **time-critical** |
| 4 | addata.gov.ae dataset inventory, currency and licence | **[UNRESOLVED]** — unreachable (TLS failure) | Verify from a UAE network |
| 5 | DoH Open Data Dashboards licensing/reuse terms | **[UNRESOLVED]** | Ask DoH before reproducing figures |
| 6 | NHANES NCHS Data User Agreement exact terms | **[UNRESOLVED]** | Read the DUA; Legal review per RAI §3.2.1.5 |
| 7 | ADHICS control tier applicable to a system like PulseReach | **[UNRESOLVED]** | Requires ADHICS Standard §A-2 + `ADHICS@doh.gov.ae` |
| 8 | Whether IFHAS invitations are centrally issued (ADPHC) or provider-issued | Partially resolved — §4.7.1 puts the Invitation System on the *provider* | Confirm operational ownership |
| 9 | Exact IFHAS 2025 expansion scope beyond what V10 contains | **[UNRESOLVED]** | Only V10 content is treated as verified |
| 10 | `ifhas.gov.ae` returned HTTP 404 | **[VERIFIED]** as non-resolving at research time | Use adphc.gov.ae programme page instead |
| 11 | Hosting region vs UAE residency requirement | **[UNRESOLVED]** — blocks any real-data deployment | Architecture decision needed (§7.2) |

---

## 9. Final report

### 1. Which sources are essential for PulseReach?
Four, and only four are load-bearing:
1. **IFHAS Standard V10/2025** — the sole approved source of adult eligibility and intervals.
2. **Well-Child Visit Standard V10/2025** — the sole approved source of the child visit schedule.
3. **Synthea** — the only practical way to get individual-level patient records legally.
4. **Responsible AI Standard V1/2025** — governance is an explicit judging criterion, and it dictates architecture (UAE residency, human oversight, explainability, opt-out).

ADHICS v2 is essential *as a constraint* on the deployment story. NHANES is useful but **not** essential. The DoH dashboards, addata.gov.ae and the trade.gov guide are contextual.

### 2. Which sources should we download?
- **Four PDFs** (IFHAS, WCV, Responsible AI, optionally Cervical Cancer) — our rule sources, already retrieved.
- **Synthea generator** (Apache 2.0) — run locally.
- **Five NHANES XPT files only** — `DEMO_L`, `BMX_L`, `BPXO_L`, `GHB_L`, `TCHOL_L`.

That is the whole list. ADHICS (286 pp) can stay a reference; we do not need it locally to build.

### 3. Which documents should only be used as references?
ADHICS v2 implementation guideline; the trade.gov commercial guide (a *foreign* government's summary — never cite it for UAE legal claims); DoH Open Data Dashboards; the ADPHC IFHAS programme page (superseded by the numbered standard for all criteria); SCAD and addata.gov.ae aggregates.

### 4. What can we obtain from Abu Dhabi DoH Open Data?
**Aggregate statistics for context only — and not as files.** The page is a set of embedded Power BI/Tableau dashboards with no download links and no published API; we verified this in the page source rather than assuming it. Separately, ~33 DoH aggregate CSVs are **reported** on `addata.gov.ae` under the Abu Dhabi Government Open Data License, but that portal was unreachable from this network (TLS handshake failure) and remains unverified. **Nothing here is individual-level, so nothing here can drive patient-level logic.**

### 5. Can NHANES support our MVP, and what are its limitations?
**Partially — for engineering, not for clinical or local claims.** It gives us free, registration-free, individual-level, de-identified measurements (BMI, waist, BP, HbA1c, lipids) that map closely onto the IFHAS Major Package, which makes it genuinely useful for building and testing the pipeline and sanity-checking model mechanics on real-world value distributions.

Its limits are hard: it is a **US** sample, so it **cannot** establish Abu Dhabi prevalence or validate local thresholds; the UAE differs materially in age structure, nationality mix and diabetes prevalence. Under RAI §3.1.5.1.1 training data must reflect the *target* population, so an NHANES-derived model is a scaffold that must be labelled as such. It contains **no** well-child, IFHAS, outreach, appointment or completion constructs, and its XPT format needs conversion. Format and free access were verified directly.

### 6. Can Synthea generate the patient records we need?
**The base layer, yes; the Abu Dhabi preventive layer, no.** Synthea gives us Apache-2.0-licensed synthetic patients with longitudinal encounters, conditions, observations (vitals/labs), medications and care plans, in FHIR R4 or CSV — which covers demographics and clinical measurement history well. But inspection of its 37 modules confirms there is **no well-child/pediatric-preventive module and no screening-programme module**: `Wellness Encounters` is a generic US-cadence wellness visit, not the DoH 14-visit schedule. It also has no outreach, appointment, opt-out, Thiqa or Emirates ID concepts.

### 7. Which records will need custom synthetic generation?
IFHAS screening records (package, band, frequency, completion); Well-Child Visit events across all 14 age points; scored instruments (M-CHAT-R, IDAQ, PHQ-9, GAD-7); outreach events (invitation, reminder, recall, **opt-out**); appointment bookings; screening completion (complete vs partial); follow-up/referral events with the standards' timing windows; defaulter/catch-up state; documented refusal state; and Thiqa eligibility plus local identifiers (Emirates ID, Abu Dhabi City / Al Ain / Al Dhafra). Full table in §6.

### 8. What requires a healthcare partner or government authorization?
Any real patient data, full stop. Specifically: **Malaffi** (HIE), **Shafafiya** (e-claims — the IFHAS reporting path), and **Sahatna**; operating under **DoH licensing** (both standards bind *licensed providers*, which we are not); **High-Risk AI conformity assessment** with DoH DDGO; a **UAE-resident hosting arrangement**; a real **consent and DPO** function; **clinical validation** of any risk logic; and NHANES **Limited Access Data** (NCHS RDC application). None of these were accessed or attempted.

### 9. What is the recommended next technical step?
**Encode the two standards' criteria as a versioned, citation-carrying rules configuration — before writing any schema or feature code.**

Concretely, as the next unit of work: create `data-pipeline/rules/` holding `ifhas_packages.yaml` (the 20 rows of IFHAS Appendix 7: package, min/max age, gender, interval, test components) and `wcv_schedule.yaml` (the 14 visit ages with per-age screening requirements, plus the M-CHAT-R/IDAQ referral tiers). Every entry carries a `source` field naming the document ref and section (e.g. `DoH/SD/ADPHC-CHS/IFHAS/V10/2025 App.7`) and a `status` field of `verified` / `unresolved`.

This is the right next step for three reasons: it is the one artifact both MVP pathways depend on; it forces the unresolved items (the >75 ceiling, the TBD effective date) to be explicit data rather than buried assumptions; and the schema design that follows should be derived from these rules, not guessed ahead of them.

**Before that, given the 20 Nov 2026 prototype date (~6 days out), confirm the submission deadline — scope depends on the answer.**

---

## 10. Source index

| # | Source | URL | Accessed |
|---|---|---|---|
| 1 | DoH Open Data Dashboards | https://www.doh.gov.ae/resources/opendata | Page source inspected |
| 1b | Abu Dhabi Open Data Platform — DoH | https://addata.gov.ae/group/department-health | **Unreachable (TLS)** |
| 2 | ADPHC IFHAS programme page | https://www.adphc.gov.ae/en/Public-Health-Programs/IFHAS | Fetched |
| 2b | **IFHAS Standard V10/2025** | https://www.doh.gov.ae/-/media/EE758C3B77314BC394F2479AEF803AA2.ashx | **PDF read (24 pp)** |
| 3 | **Well-Child Visit Standard V10/2025** | https://www.doh.gov.ae/-/media/Feature/Resources/Standards/2025/Well-Child-Visit-Standard.ashx | **PDF read (32 pp)** |
| 4 | **Responsible AI Standard V1/2025** | https://www.doh.gov.ae/-/media/Feature/Resources/Standards/2025/Responsible-AI-Standard-V1.ashx | **PDF read (15 pp)** |
| 5 | **ADHICS v2 Implementation Guideline** | https://www.doh.gov.ae/-/media/Feature/Resources/Guidelines/ADHICS-v2-implemetation-guideline.ashx | **PDF read (286 pp, targeted)** |
| 6 | UAE Digital Economy (ITA) | https://www.trade.gov/country-commercial-guides/united-arab-emirates-digital-economy | Fetched |
| 7 | CDC NHANES | https://wwwn.cdc.gov/nchs/nhanes/ | Fetched; XPT verified |
| 8 | Synthea | https://synthetichealth.github.io/synthea/ | Fetched; Apache 2.0 + modules verified |
| 9 | Future Health Digital Innovation Challenge | https://hack2skill.com/event/futurehealthchallenge/ | Fetched |
| + | Cervical Cancer Screening Standard 2025 | https://www.doh.gov.ae/-/media/Feature/Resources/Standards/2025/for-publication_-Standard-Cervical-Cancer-Screening-Standard.ashx | PDF read (14 pp) |

> **Verification note:** `doh.gov.ae` and `addata.gov.ae` presented TLS chain errors to the standard fetch tool; DoH PDFs were therefore retrieved with `curl` and verified by file signature and page count. Documents were confirmed by their internal reference numbers, not by filename. The two Well-Child Visit URLs encountered during research were confirmed byte-identical (MD5 `ddc0e540169afd4dc964d73a0c3fd7a6`).
