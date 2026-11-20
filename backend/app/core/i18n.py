"""English / Arabic backend localization (docs/localization-and-language-support.md).

- Locales: `en` (default) and `ar` (right-to-left). Codes are the only representation used in
  API contracts (`preferred_language`, `locale`, `?lang=`).
- Resolution order: `?lang=` query parameter -> authenticated user's `preferred_language` ->
  `Accept-Language` -> `DEFAULT_LOCALE`.
- Messages are complete sentences per locale with named placeholders; parameters are never
  concatenated around translated fragments. In Arabic, interpolated values (ids, dates, numbers,
  Latin names) are wrapped in Unicode first-strong isolates (U+2068 ... U+2069) so they cannot
  reorder the surrounding right-to-left text.
- Identifiers, enum values, clinical codes, rule ids and field names are never translated;
  responses carry the machine value plus a localized `*_label` / `*_display` field.
- Nothing here influences evaluation: the clinical engine never receives a locale.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, Request

from app.core.config import settings

SUPPORTED_LOCALES = ("en", "ar")
RTL_LOCALES = frozenset({"ar"})
_FSI, _PDI = "\u2068", "\u2069"

_AR_MONTHS = (
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
)
_EN_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# key -> {locale: template}. Keep both locales for every key (enforced by a test).
MESSAGES: dict[str, dict[str, str]] = {
    # --- generic errors -------------------------------------------------------------------
    "error.not_found": {"en": "The requested resource was not found.", "ar": "لم يتم العثور على المورد المطلوب."},
    "error.validation": {"en": "Invalid request: {reason}", "ar": "طلب غير صالح: {reason}"},
    "error.conflict": {"en": "The request conflicts with the current state of the resource.", "ar": "يتعارض الطلب مع الحالة الحالية للمورد."},
    "error.internal": {"en": "Internal server error.", "ar": "حدث خطأ داخلي في الخادم."},
    "error.unavailable": {"en": "The service is temporarily unavailable.", "ar": "الخدمة غير متاحة مؤقتًا."},
    "error.forbidden": {"en": "You do not have permission to perform this action.", "ar": "ليست لديك صلاحية لتنفيذ هذا الإجراء."},
    # --- authentication -------------------------------------------------------------------
    "auth.not_authenticated": {"en": "Authentication is required.", "ar": "يلزم تسجيل الدخول."},
    "auth.token_invalid": {"en": "The access token is invalid or has expired.", "ar": "رمز الوصول غير صالح أو منتهي الصلاحية."},
    "auth.invalid_credentials": {"en": "The e-mail address or password is incorrect.", "ar": "البريد الإلكتروني أو كلمة المرور غير صحيحة."},
    "auth.account_locked": {"en": "Too many failed sign-in attempts. Try again later.", "ar": "تم تجاوز عدد محاولات تسجيل الدخول المسموح بها. يُرجى المحاولة لاحقًا."},
    "auth.refresh_invalid": {"en": "The refresh token is invalid or has expired. Please sign in again.", "ar": "رمز التحديث غير صالح أو منتهي الصلاحية. يُرجى تسجيل الدخول مجددًا."},
    "auth.rate_limited": {"en": "Too many requests. Please wait and try again.", "ar": "عدد كبير جدًا من الطلبات. يُرجى الانتظار ثم المحاولة مرة أخرى."},
    "auth.registration_accepted": {"en": "If this e-mail address can be registered, the account is ready and you can sign in.", "ar": "إذا كان من الممكن تسجيل هذا البريد الإلكتروني، فإن الحساب جاهز ويمكنك تسجيل الدخول."},
    "auth.registration_disabled": {"en": "Self-registration is not available.", "ar": "التسجيل الذاتي غير متاح."},
    "auth.password_too_short": {"en": "The password must be at least {min_length} characters long.", "ar": "يجب ألا تقل كلمة المرور عن {min_length} حرفًا."},
    "auth.password_too_long": {"en": "The password is too long.", "ar": "كلمة المرور طويلة جدًا."},
    "auth.password_weak": {"en": "Choose a less predictable password that does not contain your e-mail address.", "ar": "اختر كلمة مرور يصعب تخمينها ولا تتضمن بريدك الإلكتروني."},
    "auth.password_reset_requested": {"en": "If an account exists for this address, password-reset instructions will be provided by your organization.", "ar": "إذا كان هناك حساب مرتبط بهذا العنوان، فستزوّدك جهتك بتعليمات إعادة تعيين كلمة المرور."},
    "auth.one_time_token_invalid": {"en": "The reset or activation code is invalid, expired or already used.", "ar": "رمز إعادة التعيين أو التفعيل غير صالح أو منتهي الصلاحية أو مستخدم مسبقًا."},
    "auth.current_password_invalid": {"en": "The current password is incorrect.", "ar": "كلمة المرور الحالية غير صحيحة."},
    "auth.organization_not_member": {"en": "You are not an active member of this organization.", "ar": "لست عضوًا نشطًا في هذه الجهة."},
    "auth.email_invalid": {"en": "Enter a valid e-mail address.", "ar": "أدخل بريدًا إلكترونيًا صالحًا."},
    # --- administration -------------------------------------------------------------------
    "admin.email_unavailable": {"en": "This e-mail address cannot be used.", "ar": "لا يمكن استخدام هذا البريد الإلكتروني."},
    "admin.role_not_assignable": {"en": "This role cannot be assigned here.", "ar": "لا يمكن إسناد هذا الدور هنا."},
    "admin.cannot_modify_self": {"en": "You cannot change your own role or status.", "ar": "لا يمكنك تغيير دورك أو حالتك بنفسك."},
    "admin.patient_in_other_organization": {"en": "{count} patient record(s) already belong to another organization.", "ar": "عدد السجلات المرتبطة بجهة أخرى: {count}."},
    "admin.staff_not_eligible": {"en": "The staff member is not an active care-team member of this organization.", "ar": "الموظف ليس عضوًا نشطًا في فريق الرعاية بهذه الجهة."},
    "admin.slug_unavailable": {"en": "This organization identifier is already in use.", "ar": "معرّف الجهة هذا مستخدم بالفعل."},
    # --- patient linking ------------------------------------------------------------------
    "link.invitation_invalid": {"en": "The invitation code or date of birth is not valid.", "ar": "رمز الدعوة أو تاريخ الميلاد غير صحيح."},
    "link.already_linked": {"en": "This account is already linked to a patient record.", "ar": "هذا الحساب مرتبط بالفعل بسجل مريض."},
    "link.staff_account": {"en": "Staff accounts cannot be linked to a patient record.", "ar": "لا يمكن ربط حسابات الموظفين بسجل مريض."},
    "link.completed": {"en": "Your account is now linked to your patient record.", "ar": "تم ربط حسابك بسجلك الصحي بنجاح."},
    "portal.not_linked": {"en": "Your account is not linked to a patient record yet. Use the invitation code from your care team.", "ar": "حسابك غير مرتبط بسجل مريض بعد. استخدم رمز الدعوة الذي قدّمه لك فريق الرعاية."},
    # --- workflow -------------------------------------------------------------------------
    "workflow.task_closed": {"en": "This follow-up is closed.", "ar": "تم إغلاق هذه المتابعة."},
    "workflow.invalid_transition": {"en": "The status cannot change from {from_status} to {to_status}.", "ar": "لا يمكن تغيير الحالة من {from_status} إلى {to_status}."},
    "workflow.completion_evidence_required": {"en": "Completing this follow-up requires a documented completion with verified evidence on its care gap.", "ar": "يتطلب إكمال هذه المتابعة توثيق الإنجاز بدليل موثّق على فجوة الرعاية المرتبطة بها."},
    "workflow.care_gap_not_open": {"en": "The care gap is not open for this patient.", "ar": "فجوة الرعاية غير مفتوحة لهذا المريض."},
    "workflow.appointment_change_not_allowed": {"en": "This appointment can no longer be changed online. Please contact your care team.", "ar": "لم يعد بالإمكان تغيير هذا الموعد عبر الإنترنت. يُرجى التواصل مع فريق الرعاية."},
    "workflow.request_submitted": {"en": "Your request has been sent to your care team.", "ar": "تم إرسال طلبك إلى فريق الرعاية."},
    "workflow.response_recorded": {"en": "Thank you. Your response has been sent to your care team.", "ar": "شكرًا لك. تم إرسال ردك إلى فريق الرعاية."},
    "workflow.reported_completion_pending": {"en": "Thank you. Your care team will verify this before your record is updated.", "ar": "شكرًا لك. سيتحقق فريق الرعاية من ذلك قبل تحديث سجلك."},
    # --- labels: programmes and statuses --------------------------------------------------
    "programme.ifhas": {"en": "Adult preventive screening (IFHAS)", "ar": "الفحص الوقائي الدوري للبالغين (IFHAS)"},
    "programme.well_child": {"en": "Well-child preventive care", "ar": "برنامج رعاية الطفل السليم"},
    "evaluation_status.eligible": {"en": "Available to you", "ar": "متاح لك"},
    "evaluation_status.not_eligible": {"en": "Not applicable", "ar": "لا ينطبق"},
    "evaluation_status.due": {"en": "Recommended now", "ar": "يُنصح به الآن"},
    "evaluation_status.upcoming": {"en": "Coming up soon", "ar": "قريبًا"},
    "evaluation_status.overdue": {"en": "Past the recommended time", "ar": "تجاوز الموعد الموصى به"},
    "evaluation_status.completed": {"en": "Completed", "ar": "مكتمل"},
    "evaluation_status.unknown": {"en": "No history on file", "ar": "لا يوجد سجل سابق"},
    "evaluation_status.insufficient_information": {"en": "More information needed", "ar": "يلزم مزيد من المعلومات"},
    "evaluation_status.requires_clinical_review": {"en": "Being reviewed by your care team", "ar": "قيد المراجعة من فريق الرعاية"},
    "care_gap_status.open": {"en": "Open", "ar": "مفتوحة"},
    "care_gap_status.closed_completed": {"en": "Completed", "ar": "مكتملة"},
    "care_gap_status.closed_refused": {"en": "Declined", "ar": "مرفوضة"},
    "care_gap_status.suppressed": {"en": "Paused", "ar": "معلّقة"},
    "care_gap_status.superseded": {"en": "Replaced by a newer recommendation", "ar": "استُبدلت بتوصية أحدث"},
    "history_status.available": {"en": "History available", "ar": "السجل متوفر"},
    "history_status.partial": {"en": "History partly available", "ar": "السجل متوفر جزئيًا"},
    "history_status.not_available": {"en": "No history on file", "ar": "لا يوجد سجل"},
    "appointment_status.scheduled": {"en": "Scheduled", "ar": "مجدول"},
    "appointment_status.attended": {"en": "Attended", "ar": "تم الحضور"},
    "appointment_status.no_show": {"en": "Missed", "ar": "لم يتم الحضور"},
    "appointment_status.cancelled_by_patient": {"en": "Cancelled by you", "ar": "ألغيته أنت"},
    "appointment_status.cancelled_by_facility": {"en": "Cancelled by the facility", "ar": "ألغته المنشأة"},
    "appointment_status.rescheduled": {"en": "Rescheduled", "ar": "أعيدت جدولته"},
    "appointment_type.ifhas_screening": {"en": "Preventive screening visit", "ar": "زيارة الفحص الوقائي"},
    "appointment_type.well_child_visit": {"en": "Well-child visit", "ar": "زيارة الطفل السليم"},
    "appointment_type.referral_visit": {"en": "Referral visit", "ar": "زيارة إحالة"},
    "appointment_type.other": {"en": "Other visit", "ar": "زيارة أخرى"},
    "referral_status.pending": {"en": "Pending", "ar": "قيد الانتظار"},
    "referral_status.initiated": {"en": "In progress", "ar": "قيد التنفيذ"},
    "referral_status.completed": {"en": "Completed", "ar": "مكتملة"},
    "referral_status.declined": {"en": "Declined", "ar": "مرفوضة"},
    "referral_status.cancelled": {"en": "Cancelled", "ar": "ملغاة"},
    "task_status.open": {"en": "Open", "ar": "مفتوحة"},
    "task_status.awaiting_patient": {"en": "Waiting for your reply", "ar": "بانتظار ردك"},
    "task_status.patient_responded": {"en": "Reply received", "ar": "تم استلام ردك"},
    "task_status.in_progress": {"en": "In progress", "ar": "قيد المتابعة"},
    "task_status.completed": {"en": "Completed", "ar": "مكتملة"},
    "task_status.cancelled": {"en": "Closed", "ar": "مغلقة"},
    "request_status.submitted": {"en": "Submitted", "ar": "تم الإرسال"},
    "request_status.acknowledged": {"en": "Received by your care team", "ar": "استلمه فريق الرعاية"},
    "request_status.scheduled": {"en": "Scheduled", "ar": "تمت الجدولة"},
    "request_status.declined": {"en": "Not possible", "ar": "تعذّر تنفيذه"},
    "request_status.closed": {"en": "Closed", "ar": "مغلق"},
    "request_status.cancelled": {"en": "Cancelled", "ar": "ملغى"},
    "request_type.appointment": {"en": "Appointment request", "ar": "طلب موعد"},
    "request_type.assistance": {"en": "Request for help", "ar": "طلب مساعدة"},
    "request_type.appointment_change": {"en": "Appointment change request", "ar": "طلب تعديل موعد"},
    "screening_status.complete": {"en": "Completed", "ar": "مكتمل"},
    "screening_status.partial": {"en": "Partly completed", "ar": "مكتمل جزئيًا"},
    "screening_status.not_attended": {"en": "Not attended", "ar": "لم يتم الحضور"},
    "attendance_status.attended": {"en": "Attended", "ar": "تم الحضور"},
    "attendance_status.not_attended": {"en": "Not attended", "ar": "لم يتم الحضور"},
    "response.will_book": {"en": "I will arrange it", "ar": "سأقوم بترتيب ذلك"},
    "response.already_done": {"en": "I have already done this elsewhere", "ar": "قمت بذلك بالفعل في مكان آخر"},
    "response.need_help": {"en": "I need help", "ar": "أحتاج إلى مساعدة"},
    "response.not_interested": {"en": "Not at this time", "ar": "ليس في الوقت الحالي"},
    "response.question": {"en": "I have a question", "ar": "لدي استفسار"},
    "timeline.appointment_scheduled": {"en": "An appointment was scheduled", "ar": "تمت جدولة موعد"},
    "timeline.appointment_updated": {"en": "An appointment was updated", "ar": "تم تحديث موعد"},
    "timeline.referral_created": {"en": "A referral was created", "ar": "تم إنشاء إحالة"},
    "timeline.referral_updated": {"en": "A referral was updated", "ar": "تم تحديث إحالة"},
    "timeline.completion_documented": {"en": "Completion was documented by your care team", "ar": "وثّق فريق الرعاية الإنجاز"},
    "timeline.outreach_attempted": {"en": "Your care team prepared a reminder (simulated, not sent)", "ar": "أعدّ فريق الرعاية تذكيرًا (محاكاة، لم يُرسل)"},
    "timeline.identified": {"en": "Recommendation identified", "ar": "تم تحديد التوصية"},
    "timeline.closed": {"en": "Recommendation closed", "ar": "تم إغلاق التوصية"},
    "task_event.created": {"en": "Follow-up created", "ar": "تم إنشاء المتابعة"},
    "task_event.status_changed": {"en": "Status updated", "ar": "تم تحديث الحالة"},
    "task_event.staff_message": {"en": "Message from your care team", "ar": "رسالة من فريق الرعاية"},
    "task_event.patient_response": {"en": "Your reply", "ar": "ردّك"},
    "task_event.assistance_requested": {"en": "You asked for help", "ar": "طلبت المساعدة"},
    "task_event.appointment_requested": {"en": "You requested an appointment", "ar": "طلبت موعدًا"},
    "task_event.completed": {"en": "Follow-up completed", "ar": "اكتملت المتابعة"},
    "task_event.due_date_changed": {"en": "Target date updated", "ar": "تم تحديث التاريخ المستهدف"},
    "task_event.escalated": {"en": "Escalated", "ar": "تم التصعيد"},
    "task_event.assigned": {"en": "Assigned", "ar": "تم الإسناد"},
    "task_event.staff_note": {"en": "Internal note", "ar": "ملاحظة داخلية"},
    # --- patient-facing recommendation text -----------------------------------------------
    "gap.no_documented_screening.title": {"en": "Preventive check recommended", "ar": "يُنصح بإجراء فحص وقائي"},
    "gap.no_documented_screening.description": {"en": "Our records do not show this preventive check for you in {programme}.", "ar": "لا تُظهر سجلاتنا إجراء هذا الفحص الوقائي لك ضمن {programme}."},
    "gap.interval_elapsed.title": {"en": "Time for your next preventive check", "ar": "حان موعد فحصك الوقائي التالي"},
    "gap.interval_elapsed.description": {"en": "The recommended time since your last check in {programme} has passed.", "ar": "انقضت المدة الموصى بها منذ آخر فحص لك ضمن {programme}."},
    "gap.partial_completion.title": {"en": "Part of your check is still open", "ar": "جزء من فحصك لم يكتمل بعد"},
    "gap.partial_completion.description": {"en": "Some parts of your {programme} check are not yet documented.", "ar": "بعض أجزاء فحصك ضمن {programme} غير موثّقة بعد."},
    "gap.referral_not_initiated.title": {"en": "A follow-up step is waiting", "ar": "هناك خطوة متابعة بانتظارك"},
    "gap.referral_not_initiated.description": {"en": "A follow-up step noted in your {programme} record has not been started yet.", "ar": "لم تبدأ بعد خطوة متابعة مذكورة في سجلك ضمن {programme}."},
    "gap.visit_not_attended.title": {"en": "A planned visit was missed", "ar": "فاتتك زيارة مخططة"},
    "gap.visit_not_attended.description": {"en": "A planned {programme} visit is not recorded as attended.", "ar": "لم تُسجَّل زيارة مخططة ضمن {programme} على أنها تمت."},
    "next_step.offer_screening_package": {"en": "Contact your preventive-care provider to arrange the screening.", "ar": "تواصل مع مقدّم الرعاية الوقائية لترتيب الفحص."},
    "next_step.complete_outstanding_components": {"en": "Contact your preventive-care provider to complete the remaining parts.", "ar": "تواصل مع مقدّم الرعاية الوقائية لاستكمال الأجزاء المتبقية."},
    "next_step.schedule_well_child_visit": {"en": "Contact your preventive-care provider to arrange the well-child visit.", "ar": "تواصل مع مقدّم الرعاية الوقائية لترتيب زيارة الطفل السليم."},
    "next_step.initiate_referral": {"en": "Contact your preventive-care provider about the follow-up step in your record.", "ar": "تواصل مع مقدّم الرعاية الوقائية بشأن خطوة المتابعة المذكورة في سجلك."},
    "next_step.care_team_review": {"en": "Your care team will review this and contact you if anything is needed.", "ar": "سيراجع فريق الرعاية ذلك ويتواصل معك إذا لزم الأمر."},
    "explain.why": {"en": "This recommendation was identified on {identified_date} from the information in your record.", "ar": "تم تحديد هذه التوصية بتاريخ {identified_date} استنادًا إلى المعلومات الموجودة في سجلك."},
    "explain.next_due": {"en": "The next recommended date is {next_due_date}.", "ar": "التاريخ الموصى به التالي هو {next_due_date}."},
    "explain.history_unknown": {"en": "Some of your earlier history is not on file, so your care team may ask you about previous checks.", "ar": "بعض سجلك السابق غير متوفر، لذلك قد يسألك فريق الرعاية عن الفحوصات السابقة."},
    "explain.disclaimer": {"en": "This is general information from your preventive-care programme, not a diagnosis. Please consult a licensed healthcare professional with any questions. All records in this demo are synthetic.", "ar": "هذه معلومات عامة من برنامج الرعاية الوقائية وليست تشخيصًا. يُرجى استشارة مختص رعاية صحية مرخّص لأي استفسار. جميع السجلات في هذا العرض التجريبي مُصطنعة."},
    # --- follow-up task message templates (message_key) -----------------------------------
    "task.screening_invitation": {"en": "Your care team invites you to arrange a preventive check. Reply here if you would like help or an appointment.", "ar": "يدعوك فريق الرعاية إلى ترتيب فحص وقائي. يمكنك الرد هنا إذا كنت ترغب في المساعدة أو حجز موعد."},
    "task.complete_outstanding": {"en": "Part of your preventive check is still open. Reply here to let your care team know how they can help.", "ar": "لا يزال جزء من فحصك الوقائي غير مكتمل. يمكنك الرد هنا لإبلاغ فريق الرعاية بكيفية مساعدتك."},
    "task.referral_follow_up": {"en": "Your care team would like to check in about a follow-up step in your record.", "ar": "يرغب فريق الرعاية في متابعة خطوة مذكورة في سجلك."},
    "task.well_child_visit": {"en": "Your care team invites you to arrange your child's well-child visit. Reply here if you would like help.", "ar": "يدعوك فريق الرعاية إلى ترتيب زيارة الطفل السليم لطفلك. يمكنك الرد هنا إذا كنت ترغب في المساعدة."},
    "task.general_check_in": {"en": "Your care team would like to check in with you. Reply here at any time.", "ar": "يرغب فريق الرعاية في الاطمئنان عليك. يمكنك الرد هنا في أي وقت."},
    "time_of_day.morning": {"en": "Morning", "ar": "صباحًا"},
    "time_of_day.afternoon": {"en": "Afternoon", "ar": "بعد الظهر"},
    "time_of_day.evening": {"en": "Evening", "ar": "مساءً"},
    # --- population intelligence (BE-33) --------------------------------------------------
    "population.alert_not_found": {"en": "The population alert was not found.", "ar": "لم يتم العثور على تنبيه صحة السكان."},
    "population.invalid_transition": {"en": "An alert cannot move from {from_status} to {to_status}.", "ar": "لا يمكن نقل التنبيه من {from_status} إلى {to_status}."},
    "population.area_not_found": {"en": "The geographic area was not found.", "ar": "لم يتم العثور على المنطقة الجغرافية."},
    "population.refresh_in_progress": {"en": "An aggregation for this organization is already running. Try again shortly.", "ar": "يجري حاليًا تجميع بيانات هذه الجهة. يُرجى المحاولة بعد قليل."},
    "population.condition_required": {"en": "Select a condition for the metric {metric}.", "ar": "اختر حالة مرضية للمؤشر {metric}."},
    "population.invalid_bbox": {"en": "The bounding box must be min_longitude,min_latitude,max_longitude,max_latitude.", "ar": "يجب أن يكون نطاق الخريطة بالصيغة: أدنى خط طول، أدنى خط عرض، أعلى خط طول، أعلى خط عرض."},
    "population.alert.case_increase.title": {"en": "Recorded {condition} cases increased in {area}", "ar": "ارتفعت الحالات المسجلة من {condition} في {area}"},
    "population.alert.case_increase.explanation": {"en": "{current} new recorded diagnoses in the latest {period} versus {previous} in the previous {period} (change {change}). Threshold-based signal of recorded counts; not a confirmed outbreak.", "ar": "{current} تشخيصًا جديدًا مسجلًا في آخر {period} مقابل {previous} في الفترة السابقة {period} (التغير {change}). إشارة مبنية على حدود لعدد الحالات المسجلة، وليست تفشيًا مؤكدًا."},
    "population.alert.disease_burden.title": {"en": "High recorded {condition} burden in {area}", "ar": "عبء مرتفع مسجل من {condition} في {area}"},
    "population.alert.disease_burden.explanation": {"en": "{count} patients have an active recorded {condition}, at or above the configured threshold of {threshold}.", "ar": "لدى {count} مريضًا حالة {condition} نشطة مسجلة، وهو ما يساوي الحد المحدد البالغ {threshold} أو يتجاوزه."},
    "population.alert.prevalence.title": {"en": "Recorded {condition} prevalence above threshold in {area}", "ar": "انتشار {condition} المسجل أعلى من الحد في {area}"},
    "population.alert.prevalence.explanation": {"en": "Recorded prevalence is {prevalence} of the registered population, at or above the configured {threshold}.", "ar": "يبلغ الانتشار المسجل {prevalence} من السكان المسجلين، وهو ما يساوي الحد المحدد {threshold} أو يتجاوزه."},
    "population.alert.preventive_coverage_low.title": {"en": "Preventive-care coverage below target in {area}", "ar": "تغطية الرعاية الوقائية أقل من المستهدف في {area}"},
    "population.alert.preventive_coverage_low.explanation": {"en": "{coverage} of in-scope patients have no open preventive-care gap, below the configured target of {target}.", "ar": "{coverage} من المرضى المشمولين ليست لديهم فجوة رعاية وقائية مفتوحة، وهو أقل من المستهدف المحدد البالغ {target}."},
    "population.alert.follow_up_completion_decline.title": {"en": "Follow-up completion declining in {area}", "ar": "تراجع إنجاز المتابعة في {area}"},
    "population.alert.follow_up_completion_decline.explanation": {"en": "Documented follow-up completion fell from {previous} to {current} of eligible care gaps.", "ar": "انخفض إنجاز المتابعة الموثق من {previous} إلى {current} من فجوات الرعاية المؤهلة."},
    "population.alert.facility_coverage_insufficient.title": {"en": "Limited published facility coverage in {area}", "ar": "تغطية محدودة بالمنشآت المنشورة في {area}"},
    "population.alert.facility_coverage_insufficient.explanation": {"en": "{count} care facilities (hospitals, health centres, clinics) are listed under this area's label in the official register, below the configured minimum of {threshold}. Capacity and services are not published.", "ar": "{count} منشأة رعاية (مستشفيات ومراكز صحية وعيادات) مدرجة تحت اسم هذه المنطقة في السجل الرسمي، وهو أقل من الحد الأدنى المحدد البالغ {threshold}. لا تُنشر السعة والخدمات."},
}

TASK_MESSAGE_KEYS = tuple(k.removeprefix("task.") for k in MESSAGES if k.startswith("task."))


def normalize_locale(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip().lower().replace("_", "-").split("-")[0]
    return code if code in SUPPORTED_LOCALES else None


def parse_accept_language(header: str | None) -> str | None:
    if not header:
        return None
    ranked: list[tuple[float, int, str]] = []
    for i, part in enumerate(header.split(",")):
        lang, _, params = part.strip().partition(";")
        q = 1.0
        if params.strip().startswith("q="):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                q = 0.0
        code = normalize_locale(lang)
        if code and q > 0:
            ranked.append((-q, i, code))
    return min(ranked)[2] if ranked else None


def resolve_locale(request: Request | None, user_preference: str | None = None) -> str:
    if request is not None:
        explicit = normalize_locale(request.query_params.get("lang"))
        if explicit:
            return explicit
        user_preference = user_preference or getattr(request.state, "user_locale", None)
    if normalize_locale(user_preference):
        return normalize_locale(user_preference)  # type: ignore[return-value]
    if request is not None:
        header = parse_accept_language(request.headers.get("accept-language"))
        if header:
            return header
    return settings.default_locale


def direction(locale: str) -> str:
    return "rtl" if locale in RTL_LOCALES else "ltr"


def _isolate(value: Any, locale: str) -> str:
    text = str(value)
    return f"{_FSI}{text}{_PDI}" if locale in RTL_LOCALES else text


def t(key: str, locale: str = "en", **params: Any) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    template = entry.get(locale) or entry["en"]
    return template.format(**{k: _isolate(v, locale) for k, v in params.items()})


def label(prefix: str, value: str | None, locale: str) -> str | None:
    if value is None:
        return None
    key = f"{prefix}.{value}"
    return t(key, locale) if key in MESSAGES else value


def format_date(value: date | datetime | None, locale: str) -> str | None:
    """Day month-name year, Western digits (as used in UAE government Arabic content)."""
    if value is None:
        return None
    months = _AR_MONTHS if locale == "ar" else _EN_MONTHS
    return f"{value.day} {months[value.month - 1]} {value.year}"


def format_datetime(value: datetime | None, locale: str) -> str | None:
    if value is None:
        return None
    return f"{format_date(value, locale)} {value.strftime('%H:%M')}"


def locale_meta(locale: str) -> dict[str, str]:
    return {"locale": locale, "direction": direction(locale)}


class AppError(HTTPException):
    """HTTPException with a catalog key: `detail` stays the stable English text, while
    `error.message` is localized and `error.message_key` identifies the message."""

    def __init__(
        self,
        status_code: int,
        message_key: str,
        *,
        params: dict[str, Any] | None = None,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message_key = message_key
        self.params = params or {}
        super().__init__(
            status_code=status_code,
            detail=detail if detail is not None else t(message_key, "en", **self.params),
            headers=headers,
        )
