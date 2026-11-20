# PulseReach — English / Arabic terminology glossary

Shared by the frontend catalogs (`frontend/lib/i18n/messages/{en,ar}.ts`) and the backend catalog
(`backend/app/core/i18n.py`). Use these renderings consistently; add a row before introducing a
new recurring term. Modern Standard Arabic; Western digits; Gregorian month names.

> These translations have not been reviewed by an Arabic clinical language specialist. They must be
> reviewed before any real-world clinical deployment. Clinical meaning (eligibility, recommendations,
> evidence, screening) must never change in translation.

| English | Arabic | Notes |
|---|---|---|
| care gap | فجوة الرعاية (pl. فجوات الرعاية) | backend catalog |
| documented gap | فجوة موثّقة | staff status vocabulary |
| follow-up | متابعة | |
| care team | فريق الرعاية | |
| care coordination | تنسيق الرعاية | |
| organization | الجهة | as in backend messages ("جهتك") |
| programme | برنامج | IFHAS / Well-Child names keep their Latin acronym |
| preventive check / screening | فحص وقائي | |
| well-child visit | زيارة الطفل السليم | |
| appointment | موعد | |
| referral | إحالة | |
| patient | مريض | |
| population health | صحة السكان | |
| eligibility / eligible | أهلية / مؤهل | never claim eligibility the engine did not decide |
| in scope (rule) | ضمن النطاق | |
| outside rule scope | خارج نطاق القاعدة | |
| evidence | دليل (pl. أدلة) | "verified evidence" = دليل موثّق |
| clinical review | مراجعة سريرية | |
| history unavailable | السجل غير متوفر | |
| synthetic (data) | مُصطنعة | "Synthetic demonstration data" = بيانات عرض تجريبية مُصطنعة |
| licensed healthcare professional | مختص رعاية صحية مرخّص | required wording in patient-facing Arabic (`مختص`) |
| audit log | سجل التدقيق | |
| role / permission | الدور / الصلاحية | permission ids (`rules.read`) stay untranslated |
| sign in / sign out | تسجيل الدخول / تسجيل الخروج | |
| API | الواجهة البرمجية | "PulseReach API" = واجهة PulseReach البرمجية |

## Roles

| Role id | English | Arabic |
|---|---|---|
| `POPULATION_HEALTH_MANAGER` | Population health manager | مدير صحة السكان |
| `CARE_COORDINATOR` | Care coordinator | منسّق الرعاية |
| `CLINICIAN` | Clinician | مختص سريري |
| `SYSTEM_ADMIN` | System administrator | مسؤول النظام |
| `PATIENT` | Patient | مريض |

## Never translated

Identifiers and codes (patient ids, rule ids such as `IFHAS-PKG-ORAL`, evaluation run ids),
enum values, permission ids, API paths, e-mail addresses, URLs, environment flags, the product
name *PulseReach*. They render left-to-right inside Arabic text (`.ltr-value`, `<bdi>` or Unicode
isolates).
