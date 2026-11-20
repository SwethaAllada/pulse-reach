"""Output validation for model-generated text. Any violation means the output is discarded and
the deterministic template is used instead."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

_EMIRATES_ID_RE = re.compile(r"\b784-?\d{4}-?\d{7}-?\d\b")
_PHONE_RE = re.compile(r"\+\d{3}[\s-]?\d|\b\d{2,3}[\s-]\d{3}[\s-]\d{4}\b|\b\d{9,}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_CLINICAL_CLAIM_RE = re.compile(
    r"\b(diagnos\w*|you have|has (?:cancer|diabetes|hypertension)|cancer|tumou?r|malignan\w*|"
    r"prescri\w*|dosage|medication|treatment plan|cure)\b",
    re.IGNORECASE,
)
_RISK_RE = re.compile(
    r"\b(risk|likel(?:y|ihood)|probabilit\w*|chance|odds|predict\w*|%|per ?cent)\b", re.IGNORECASE
)
_OVERDUE_RE = re.compile(r"\boverdue\b", re.IGNORECASE)
_APPROVAL_RE = re.compile(r"\b(clinically (?:approved|validated)|authoritative recommendation)\b", re.IGNORECASE)
# Positive status assertions; negated phrasing ("has not been completed", "is not due") passes.
_COMPLETED_RE = re.compile(
    r"(?<!not )(?<!never )\b(?:has|have|had|been|was|were|is|are)\s+(?:already\s+)?"
    r"(?:completed|up[ -]to[ -]date)\b|(?<!not )\bup[ -]to[ -]date\b",
    re.IGNORECASE,
)
_DUE_RE = re.compile(r"(?<!not )\b(?:is|are|now|currently)\s+due\b", re.IGNORECASE)
_ELIGIBLE_RE = re.compile(
    r"\b(?:is|are|remains|considered|deemed)\s+eligible\b|\bmeets?\s+(?:all\s+|the\s+)?(?:\w+\s+)?"
    r"(?:eligibility|criteria)\b",
    re.IGNORECASE,
)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUMBER_RE.findall(text)}


def allowed_numbers(facts: Any) -> set[str]:
    return _numbers(json.dumps(facts, default=str))


def validate_output(
    text: str | None,
    *,
    facts: Any,
    max_chars: int,
    must_contain: Iterable[str] = (),
    allow_risk_words: bool = False,
    allow_overdue: bool = False,
    allow_approval_claims: bool = False,
    allow_completed: bool = True,
    allow_due: bool = True,
    allow_eligibility: bool = True,
) -> list[str]:
    """Return the list of violations (empty = acceptable)."""
    if not text or not text.strip():
        return ["empty_output"]
    out: list[str] = []
    if len(text) > max_chars:
        out.append("too_long")
    if _EMIRATES_ID_RE.search(text) or _EMAIL_RE.search(text) or _PHONE_RE.search(text):
        out.append("personal_identifier")
    if _URL_RE.search(text):
        out.append("link")
    if _CLINICAL_CLAIM_RE.search(text):
        out.append("clinical_claim")
    if not allow_risk_words and _RISK_RE.search(text):
        out.append("risk_or_probability")
    if not allow_overdue and _OVERDUE_RE.search(text):
        out.append("overdue_claim")
    if not allow_approval_claims and _APPROVAL_RE.search(text):
        out.append("approval_claim")
    if not allow_completed and _COMPLETED_RE.search(text):
        out.append("completed_claim")
    if not allow_due and _DUE_RE.search(text):
        out.append("due_claim")
    if not allow_eligibility and _ELIGIBLE_RE.search(text):
        out.append("eligibility_claim")
    invented = _numbers(text) - allowed_numbers(facts)
    if invented:
        out.append("invented_number")
    for needle in must_contain:
        if needle not in text:
            out.append(f"missing:{needle}")
    return out


# --- patient-facing outreach --------------------------------------------------------------

_RECORD_ID_RE = re.compile(r"\bSYNTH-[A-Z]+-\d+\b")
_COERCIVE_RE = re.compile(
    r"\b(must|required|requirement|mandatory|obligat\w*|have to|has to|deadline|urgent\w*|"
    r"immediately|as soon as possible|asap|last chance|final (?:notice|reminder)|penalt\w*|"
    r"fined?|consequences?|failure to|do not ignore)\b",
    re.IGNORECASE,
)
_FEAR_RE = re.compile(
    r"\b(danger\w*|serious(?:ly)?|life[- ]threatening|die|dying|death|deadly|fatal|worr\w*|"
    r"afraid|fear\w*|alarming|scar(?:y|ed)|harm\w*)\b",
    re.IGNORECASE,
)
_LOGISTICS_RE = re.compile(
    r"\b(appointments?|booked|booking|reserved|slot|clinic|hospital|health cent(?:re|er)|"
    r"cent(?:re|er)|facility|branch|address|located|location|free of charge|at no cost|"
    r"no charge|costs?|fees?|price|paid|payment|aed|dirhams?|insurance|covered|today|tomorrow|"
    r"tonight|this week|next week|weekend|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday|january|february|march|april|june|july|august|september|october|november|"
    r"december|a\.m\.|p\.m\.|o'clock|call us on|reply)\b",
    re.IGNORECASE,
)
_MARKDOWN_RE = re.compile(r"(^\s*[-*#>]|\*\*|__|`)", re.MULTILINE)

# Arabic equivalents of the outreach rules. Arabic attaches prefixes (ال، و، ب، ل) to words, so
# these are substring patterns rather than word-boundary patterns. Eastern Arabic digits are
# normalized to ASCII before the invented-number check.
_AR_CHECKS = (
    (re.compile(r"تشخيص|سرطان|ورم|خبيث|مرض السكري|ضغط الدم المرتفع|وصفة|دواء|أدوية|جرعة|خطة علاج|علاج|شفاء"), "clinical_claim"),
    (re.compile(r"خطر|مخاطر|احتمال|أرجح|مرجّح|نسبة|٪|بالمئة|في المائة|توقع|تنبؤ"), "risk_or_probability"),
    (re.compile(r"متأخر|تأخرت|فات موعد"), "overdue_claim"),
    (re.compile(r"معتمد سريريًا|معتمد سريريا|توصية رسمية"), "approval_claim"),
    (re.compile(r"(?<!غير )(?<!لم ي)مكتمل|أكملت|أتممت|محدّث|محدث"), "completed_claim"),
    (re.compile(r"(?<!غير )مستحق|حان موعد"), "due_claim"),
    (re.compile(r"(?<!غير )مؤهل|أهليتك|تستوفي|معايير"), "eligibility_claim"),
    (re.compile(r"يجب|إلزامي|إجباري|مطلوب|ملزم|موعد نهائي|عاجل|فورًا|فورا|حالًا|في أقرب وقت|آخر فرصة|"
                r"إشعار أخير|تذكير أخير|غرامة|عقوبة|عواقب|لا تتجاهل"), "coercive_or_requirement"),
    (re.compile(r"خطير|خطورة|يهدد الحياة|وفاة|موت|يموت|مميت|قاتل|قلق|تقلق|خوف|تخاف|مخيف|مقلق|ضرر|أذى"), "fear_language"),
    (re.compile(r"موعد|مواعيد|حجز|محجوز|عيادة|مستشفى|مركز صحي|مركز|منشأة|فرع|عنوان|موقع|مجان|بدون تكلفة|"
                r"تكلفة|رسوم|سعر|دفع|درهم|تأمين|مغطى|اليوم|غدًا|غدا|الليلة|هذا الأسبوع|الأسبوع القادم|"
                r"عطلة نهاية الأسبوع|الاثنين|الثلاثاء|الأربعاء|الخميس|الجمعة|السبت|الأحد|يناير|فبراير|مارس|"
                r"أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر|صباحًا|مساءً|اتصل بنا|رد على"), "invented_logistics"),
)
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_ALLOWED_LATIN_IN_AR = frozenset({"IFHAS"})
_ARABIC_LETTER_RE = re.compile(r"[\u0600-\u06FF]")
_EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NON_LATIN_LETTER_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u0400-\u04FF\u4E00-\u9FFF]")
_SINGLE_PARAGRAPH_CHANNELS = frozenset({"sms", "app", "phone"})


def validate_outreach_output(
    text: str | None, *, facts: Any, channel: str, language: str, max_chars: int
) -> list[str]:
    """Shared checks plus outreach rules: no status/eligibility claims, record ids, coercion,
    fear, invented logistics (appointments, facilities, costs, dates), channel format, language."""
    arabic = language == "ar"
    if arabic and text:
        text = text.translate(_EASTERN_DIGITS)
    out = validate_output(
        text, facts=facts, max_chars=max_chars, must_contain=("مختص",) if arabic else ("professional",),
        allow_completed=False, allow_due=False, allow_eligibility=False,
    )
    if not text or not text.strip():
        return out
    checks = (
        (_RECORD_ID_RE, "personal_identifier"),
        (_COERCIVE_RE, "coercive_or_requirement"),
        (_FEAR_RE, "fear_language"),
        (_LOGISTICS_RE, "invented_logistics"),
        (_MARKDOWN_RE, "format_markdown"),
    )
    out += [v for rx, v in checks if rx.search(text) and v not in out]
    if channel in _SINGLE_PARAGRAPH_CHANNELS and "\n" in text.strip():
        out.append("format_line_breaks")
    if language == "en" and _NON_LATIN_LETTER_RE.search(text):
        out.append("language_mismatch")
    if arabic:
        out += [v for rx, v in _AR_CHECKS if rx.search(text) and v not in out]
        latin = {w for w in _LATIN_WORD_RE.findall(text) if w not in _ALLOWED_LATIN_IN_AR}
        if latin or not _ARABIC_LETTER_RE.search(text):
            out.append("language_mismatch")
    return out


# --- patient-facing assistant -------------------------------------------------------------

_SENT_RE = re.compile(
    r"\b(?:has|have|had|was|were|been)\s+(?:already\s+)?sent\b|\bwe(?:'ve| have)?\s+sent\b|"
    r"\bwill\s+(?:send|text|e-?mail)\s+you\b",
    re.IGNORECASE,
)
_BOOKING_RE = re.compile(
    r"\b(?:is|are|was|were|has been|have been)\s+(?:now\s+|already\s+)?(?:confirmed|booked|reserved)\b|"
    r"\b(?:i|we)(?:'ve| have)?\s+(?:booked|confirmed|reserved|scheduled)\b",
    re.IGNORECASE,
)
_DATE_WORD_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|"
    r"june|july|august|september|october|november|december|today|tomorrow|tonight|"
    r"next (?:week|month))\b|الاثنين|الثلاثاء|الأربعاء|الخميس|الجمعة|السبت|الأحد|يناير|فبراير|مارس|"
    r"أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر|غدًا|غدا|الليلة|الأسبوع القادم",
    re.IGNORECASE,
)
_AR_ASSISTANT_CHECKS = tuple(
    (rx, v) for rx, v in _AR_CHECKS
    if v not in ("coercive_or_requirement", "invented_logistics")  # appointments are a legitimate topic
) + (
    (re.compile(r"تم إرسال|تم الإرسال|أُرسلت|أرسلنا|سنرسل"), "sent_claim"),
    (re.compile(r"تم تأكيد|مؤكَّد|مؤكد|تم حجز|حجزنا"), "booking_claim"),
)


def validate_patient_assistant_output(
    text: str | None, *, facts: Any, language: str, max_chars: int, allow_completed: bool
) -> list[str]:
    """Shared checks plus patient-assistant rules: no status/eligibility/due claims, no record ids,
    no fear language, no claims that something was sent or booked, no dates or weekdays that are
    not in the facts, plain text in the requested language."""
    arabic = language == "ar"
    if arabic and text:
        text = text.translate(_EASTERN_DIGITS)
    out = validate_output(
        text, facts=facts, max_chars=max_chars, allow_completed=allow_completed, allow_due=False,
        allow_eligibility=False,
    )
    if not text or not text.strip():
        return out
    checks = (
        (_RECORD_ID_RE, "personal_identifier"),
        (_FEAR_RE, "fear_language"),
        (_MARKDOWN_RE, "format_markdown"),
        (_SENT_RE, "sent_claim"),
        (_BOOKING_RE, "booking_claim"),
    )
    out += [v for rx, v in checks if rx.search(text) and v not in out]
    known = json.dumps(facts, default=str, ensure_ascii=False).lower()
    if any(w.lower() not in known for w in _DATE_WORD_RE.findall(text)):
        out.append("invented_date")
    if not arabic and _NON_LATIN_LETTER_RE.search(text):
        out.append("language_mismatch")
    if arabic:
        out += [v for rx, v in _AR_ASSISTANT_CHECKS if rx.search(text) and v not in out
                and not (v == "completed_claim" and allow_completed)]
        latin = {w for w in _LATIN_WORD_RE.findall(text) if w.lower() not in known}
        if (latin or not _ARABIC_LETTER_RE.search(text)) and "language_mismatch" not in out:
            out.append("language_mismatch")
    return out


# --- untrusted input screening (before any provider call) -----------------------------------

_INJECTION_RE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,40}\b(?:instruction|rule|prompt|guideline|"
    r"polic|previous|above|earlier|system)\w*|\bsystem\s*prompt\b|\b(?:developer|admin|god|dan|debug)\s+mode\b|"
    r"\byou\s+are\s+now\b|\b(?:act|behave)\s+as\b|\bpretend\s+(?:to\s+be|you)\b|\bjailbreak\w*\b|"
    r"\b(?:reveal|show|print|repeat|output|tell me)\b.{0,30}\b(?:instruction|prompt|rule|config\w*|"
    r"secret|api\s*key)\w*|\bnew\s+(?:instructions|rules|role)\b|</?\s*(?:system|assistant|instructions?)\s*>|"
    r"\bFACTS:|\bPATIENT_QUESTION\b|"
    r"تجاهل.{0,30}(?:التعليمات|القواعد|الأوامر|السابق)|تعليمات النظام|موجه النظام|تظاهر بأنك|أنت الآن|"
    r"اكشف.{0,20}(?:التعليمات|القواعد|المفتاح)|وضع المطور",
    re.IGNORECASE | re.DOTALL,
)
_EMERGENCY_RE = re.compile(
    r"\b(?:emergenc\w*|chest\s+pain|can'?t\s+breathe|cannot\s+breathe|short(?:ness)?\s+of\s+breath|"
    r"suicid\w*|kill\s+myself|self[- ]harm|overdos\w*|unconscious|faint(?:ed|ing)|stroke|heart\s+attack|"
    r"severe\s+(?:pain|bleeding)|bleeding\s+heavily|seizure)\b|"
    r"طوارئ|ألم في الصدر|ألم بالصدر|ضيق (?:في )?التنفس|لا أستطيع التنفس|انتحار|أقتل نفسي|إيذاء النفس|جرعة زائدة|"
    r"فقدان الوعي|إغماء|جلطة|نوبة قلبية|نزيف",
    re.IGNORECASE,
)
_CLINICAL_QUESTION_RE = re.compile(
    r"\b(?:do\s+i\s+have|have\s+i\s+got|am\s+i\s+(?:sick|ill|at\s+risk)|diagnos\w*|what(?:'s|\s+is)\s+wrong\s+with\s+me|"
    r"should\s+i\s+(?:take|stop|start)|dos(?:e|age)|medicin\w*|medicat\w*|prescri\w*|treat(?:ment)?s?|"
    r"symptoms?|test\s+results?|my\s+results?|cancer|tumou?r|diabet\w*|blood\s+pressure|cholesterol)\b|"
    r"هل (?:لدي|عندي|أنا مصاب)|تشخيص|ماذا بي|دواء|أدوية|جرعة|علاج|أعراض|نتائج (?:التحليل|الفحص)|نتيجتي|سرطان|"
    r"ورم|السكري|ضغط الدم|الكوليسترول",
    re.IGNORECASE,
)
_OTHER_PERSON_RE = re.compile(
    r"\b(?:other|another|all|every)\s+(?:patients?|people|persons?|members?)\b|\bsomeone\s+else'?s?\b|"
    r"\bmy\s+(?:wife|husband|son|daughter|child|mother|father|friend|neighbou?r)'?s?\b|"
    r"\b(?:his|her|their)\s+(?:record|results?|appointments?)\b|"
    r"مرضى آخرين|مريض آخر|جميع المرضى|شخص آخر|زوجتي|زوجي|ابني|ابنتي|أمي|أبي|صديقي",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def sanitize_question(text: str) -> str:
    """Strip control / bidi-override characters and collapse whitespace (length is schema-bounded)."""
    return re.sub(r"\s+", " ", _CONTROL_RE.sub(" ", text)).strip()


def screen_question(text: str) -> str | None:
    """Classify a person's free-text question before it can reach a model.

    Returns None (may be answered from the facts) or the reason it is answered deterministically
    without any provider call: `emergency` (urgent-help escalation first), `prompt_injection`,
    `other_person` or `clinical_question`."""
    if _EMERGENCY_RE.search(text):
        return "emergency"
    if _INJECTION_RE.search(text):
        return "prompt_injection"
    if _OTHER_PERSON_RE.search(text):
        return "other_person"
    if _CLINICAL_QUESTION_RE.search(text):
        return "clinical_question"
    return None


# Model output that echoes the prompt scaffolding or claims an action was taken by the assistant.
_LEAK_RE = re.compile(
    r"\bFACTS:|PATIENT_QUESTION|untrusted text|system (?:prompt|instruction)s?|my instructions|"
    r"Use ONLY the facts|these instructions|التعليمات التي|تعليمات النظام",
    re.IGNORECASE,
)
_AGENT_ACTION_RE = re.compile(
    r"\b(?:i|we)(?:'ve|'ll| have| will| just)?\s+(?:already\s+)?(?:booked|scheduled|sent|messaged|texted|"
    r"e-?mailed|contacted|called|referred|completed|closed|updated|marked|changed|cancelled|approved)\b|"
    r"\b(?:has|have)\s+been\s+(?:sent|booked|referred|marked\s+(?:as\s+)?complete\w*)\b|"
    r"قمت ب(?:حجز|إرسال|تحديث|إغلاق|إلغاء)|تم (?:إرسال|حجز|الإرسال|الحجز|الإحالة|إغلاق)|أرسلت|حجزت",
    re.IGNORECASE,
)


def validate_portal_answer(
    text: str | None, *, facts: Any, language: str, max_chars: int, allow_completed: bool = False
) -> list[str]:
    """Patient-assistant rules plus no prompt leakage and no claims that the assistant acted."""
    out = validate_patient_assistant_output(
        text, facts=facts, language=language, max_chars=max_chars, allow_completed=allow_completed
    )
    if text and text.strip():
        out += [v for rx, v in ((_LEAK_RE, "prompt_leak"), (_AGENT_ACTION_RE, "action_claim"))
                if rx.search(text) and v not in out]
    return out


# --- staff copilot (structured JSON output) ---------------------------------------------------

COPILOT_LIMITS = {"summary": 500, "item": 220, "points": 6, "questions": 5}
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_copilot_output(text: str | None) -> dict[str, Any] | None:
    """Strict parse of `{"summary": str, "points": [str], "questions": [str]}`; None if malformed.
    Model JSON is never trusted: unknown keys, wrong types or exceeded limits are rejected."""
    if not text or not text.strip():
        return None
    try:
        data = json.loads(_FENCE_RE.sub("", text.strip()))
    except ValueError:
        return None
    if not isinstance(data, dict) or set(data) - {"summary", "points", "questions"}:
        return None
    summary, points, questions = data.get("summary"), data.get("points", []), data.get("questions", [])
    if not isinstance(summary, str) or not summary.strip() or len(summary) > COPILOT_LIMITS["summary"]:
        return None
    for items, limit in ((points, COPILOT_LIMITS["points"]), (questions, COPILOT_LIMITS["questions"])):
        if (not isinstance(items, list) or len(items) > limit
                or any(not isinstance(i, str) or not i.strip() or len(i) > COPILOT_LIMITS["item"] for i in items)):
            return None
    return {"summary": summary.strip(), "points": [p.strip() for p in points],
            "questions": [q.strip() for q in questions]}


def validate_copilot_output(text: str | None, *, facts: Any, language: str) -> list[str]:
    """Structure first, then every text field: no clinical/risk/eligibility/completion claims, no
    invented numbers, identifiers, links, markdown, prompt leakage or claims that anything was done."""
    parsed = parse_copilot_output(text)
    if parsed is None:
        return ["invalid_structure"]
    arabic = language == "ar"
    known = json.dumps(facts, default=str, ensure_ascii=False).lower()
    out: list[str] = []
    for field_text in [parsed["summary"], *parsed["points"], *parsed["questions"]]:
        t = field_text.translate(_EASTERN_DIGITS) if arabic else field_text
        found = validate_output(t, facts=facts, max_chars=COPILOT_LIMITS["summary"], allow_completed=False,
                                allow_eligibility=False)
        found += [v for rx, v in ((_MARKDOWN_RE, "format_markdown"), (_LEAK_RE, "prompt_leak"),
                                  (_AGENT_ACTION_RE, "action_claim"), (_SENT_RE, "sent_claim"))
                  if rx.search(t)]
        if not arabic and _NON_LATIN_LETTER_RE.search(t):
            found.append("language_mismatch")
        if arabic:
            found += [v for rx, v in _AR_ASSISTANT_CHECKS if rx.search(t)]
            if any(w.lower() not in known for w in _LATIN_WORD_RE.findall(t)) or not _ARABIC_LETTER_RE.search(t):
                found.append("language_mismatch")
        out += [v for v in found if v not in out]
    return out
