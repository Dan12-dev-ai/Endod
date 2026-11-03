"""Commands patients text to the short code (Option B: the patient pulls; docs/sms.md).

``handle(provider, message_id, sender, text)`` answers one received text with
the reply to send back (or None), whatever the SMS provider (api_sms.py has
the adapters). Commands, case-insensitive, with Amharic aliases:

* ``CARD <PIN>``: the Endod ID (card number);
* ``APPT <PIN>``: the next appointments and follow-ups;
* ``RESULT <PIN>``: the latest lab results, three per reply (test, value,
  unit, low/normal/high); ``RESULT 2 <PIN>`` the three before, and so on;
* ``REPORT <PIN>``: the latest report's title and conclusion (never a file);
  ``REPORT 2 <PIN>`` the one before;
* ``RX <PIN>``: pickup codes of prescriptions still open;
* ``PIN <old> <new>``: change the PIN;
* ``HELP`` (or anything else): the commands.

Rules:

* The sender's phone must be an account's *verified* phone (an active,
  unsuspended account); any other number gets one generic "not registered"
  reply a day at most, and nothing about any account.
* Every command but HELP needs the PIN (sms_pin.py: an HMAC, five wrong PINs
  lock it for an hour, and the patient is told by SMS).
* Rate limits per sender phone and for all senders (``throttle``, in the
  database); over them, no reply.
* Sensitive results are never sent, even on request: a test with a LOINC
  code, or a test or report whose words or ICD-10 code are in the
  settings' lists (HIV, pregnancy, sexually transmitted infections, mental
  health; sms_settings) is replaced with "only available at the hospital or
  in the app".
* Replies are in the account's language (Amharic or English), at most
  ``SMS_REPLY_MAX_SEGMENTS`` segments (Amharic: 67 characters a segment).
* Every text received is audited (``sms_inbound_messages``): the command, the
  outcome, the masked phone and the account. Never the text, the PIN or the
  reply, and nothing clinical is logged.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dedan_platform import sms_pin, sms_segments, sms_settings, throttle
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import (
    Appointment, EventStatus, FollowUp, HospitalRecord, PartnerHospital, Preferences, Prescription, Profile,
    SmsInboundMessage, User, utcnow,
)
from dedan_platform.phone import mask, normalise_ethiopian_mobile
from dedan_platform.sms_provider import BRAND_NAME as BRAND

logger = logging.getLogger(__name__)

ZONE = ZoneInfo("Africa/Addis_Ababa")
REPORT_CATEGORIES = ("imaging", "visit_note", "diagnosis", "document")
MAX_PAGE = 20

CARD, APPT, RESULT, REPORT, RX, PIN, HELP = "CARD", "APPT", "RESULT", "REPORT", "RX", "PIN", "HELP"
ALIASES: Dict[str, str] = {
    "CARD": CARD, "ID": CARD, "ካርድ": CARD, "መታወቂያ": CARD,
    "APPT": APPT, "APPOINTMENT": APPT, "VISIT": APPT, "ቀጠሮ": APPT,
    "RESULT": RESULT, "RESULTS": RESULT, "LAB": RESULT, "ውጤት": RESULT,
    "REPORT": REPORT, "ሪፖርት": REPORT,
    "RX": RX, "PRESCRIPTION": RX, "MED": RX, "MEDS": RX, "መድሃኒት": RX, "መድኃኒት": RX,
    "PIN": PIN, "ፒን": PIN,
    "HELP": HELP, "?": HELP, "እርዳታ": HELP,
}

T: Dict[str, Dict[str, str]] = {
    "en": {
        "help": "{brand} SMS: send CARD, APPT, RESULT, REPORT or RX followed by your PIN, e.g. RESULT 1234. "
                "RESULT 2 1234 shows older results. To change your PIN: PIN old new.",
        "help_no_pin": "{brand}: you have no SMS PIN yet. Ask at your hospital, or set one in the {brand} app.",
        "unknown_sender": "{brand}: this number is not registered for {brand} SMS. Ask at your hospital to join.",
        "format": "{brand}: send the command and your 4-digit PIN, e.g. {command} 1234. Send HELP for the list.",
        "wrong_pin": "{brand}: wrong PIN. {left} tries left before it is locked for an hour.",
        "locked_now": "{brand}: too many wrong PINs. Your PIN is locked until {until}. If this was not you, "
                      "tell your hospital.",
        "locked": "{brand}: your PIN is locked until {until}.",
        "card": "{brand}: your Endod card number (Endod ID) is {card}.",
        "no_appt": "{brand}: you have no upcoming visits.",
        "appt_head": "{brand} visits:",
        "appt": "{when} visit at {where}",
        "appt_nowhere": "{when} visit",
        "follow_up": "{when} follow-up at {where}",
        "results_head": "{brand} lab results:",
        "no_results": "{brand}: you have no lab results yet.",
        "no_more_results": "{brand}: no older lab results.",
        "more_results": "Older: RESULT {page} and your PIN",
        "withheld": "{date}: this result is only available at the hospital or in the app.",
        "no_reports": "{brand}: you have no reports yet.",
        "no_more_reports": "{brand}: no older reports.",
        "more_reports": "Older: REPORT {page} and your PIN",
        "report_withheld": "{brand} {date}: this report is only available at the hospital or in the app.",
        "no_rx": "{brand}: you have no prescriptions to collect.",
        "rx_head": "{brand} prescriptions (show the code and your phone number at the pharmacy):",
        "rx": "Code {code}, until {until}, {hospital}",
        "pin_changed": "{brand}: your PIN was changed. If this was not you, tell your hospital.",
        "pin_weak": "{brand}: choose 4 digits that are not all the same and not like 1234. "
                    "Send PIN, your old PIN and the new one.",
        "pin_format": "{brand}: to change your PIN send PIN, your old PIN and the new one, e.g. PIN 4821 7395.",
    },
    "am": {
        "help": "{brand} SMS፦ CARD፣ APPT፣ RESULT፣ REPORT ወይም RX ከፒንዎ ጋር ይላኩ፤ ለምሳሌ RESULT 1234። "
                "የቆዩ ውጤቶች፦ RESULT 2 1234። ፒን ለመቀየር፦ PIN የድሮ አዲስ።",
        "help_no_pin": "{brand}፦ እስካሁን የSMS ፒን የለዎትም። ሆስፒታልዎን ይጠይቁ ወይም በ{brand} መተግበሪያ ያስቀምጡ።",
        "unknown_sender": "{brand}፦ ይህ ቁጥር ለ{brand} SMS አልተመዘገበም። ለመመዝገብ ሆስፒታልዎን ይጠይቁ።",
        "format": "{brand}፦ ትዕዛዙን እና ባለ 4 አሃዝ ፒንዎን ይላኩ፤ ለምሳሌ {command} 1234። ዝርዝሩን ለማየት HELP ይላኩ።",
        "wrong_pin": "{brand}፦ የተሳሳተ ፒን። ለአንድ ሰዓት ከመቆለፉ በፊት {left} ሙከራ ቀርቷል።",
        "locked_now": "{brand}፦ ብዙ የተሳሳቱ ፒኖች። ፒንዎ እስከ {until} ተቆልፏል። እርስዎ ካልሆኑ ሆስፒታልዎን ያሳውቁ።",
        "locked": "{brand}፦ ፒንዎ እስከ {until} ተቆልፏል።",
        "card": "{brand}፦ የEndod ካርድ ቁጥርዎ (Endod ID) {card} ነው።",
        "no_appt": "{brand}፦ የሚመጣ ቀጠሮ የለዎትም።",
        "appt_head": "{brand} ቀጠሮዎች፦",
        "appt": "{when} ቀጠሮ፣ {where}",
        "appt_nowhere": "{when} ቀጠሮ",
        "follow_up": "{when} ክትትል፣ {where}",
        "results_head": "{brand} የላብራቶሪ ውጤቶች፦",
        "no_results": "{brand}፦ እስካሁን የላብራቶሪ ውጤት የለዎትም።",
        "no_more_results": "{brand}፦ የቆየ የላብራቶሪ ውጤት የለም።",
        "more_results": "የቆዩ፦ RESULT {page} እና ፒንዎ",
        "withheld": "{date}፦ ይህ ውጤት በሆስፒታሉ ወይም በመተግበሪያው ብቻ ይገኛል።",
        "no_reports": "{brand}፦ እስካሁን ሪፖርት የለዎትም።",
        "no_more_reports": "{brand}፦ የቆየ ሪፖርት የለም።",
        "more_reports": "የቆየ፦ REPORT {page} እና ፒንዎ",
        "report_withheld": "{brand} {date}፦ ይህ ሪፖርት በሆስፒታሉ ወይም በመተግበሪያው ብቻ ይገኛል።",
        "no_rx": "{brand}፦ የሚወሰድ የመድኃኒት ማዘዣ የለዎትም።",
        "rx_head": "{brand} ማዘዣዎች (ኮዱን ከስልክ ቁጥርዎ ጋር በፋርማሲ ያሳዩ)፦",
        "rx": "ኮድ {code}፣ እስከ {until}፣ {hospital}",
        "pin_changed": "{brand}፦ ፒንዎ ተቀይሯል። እርስዎ ካልሆኑ ሆስፒታልዎን ያሳውቁ።",
        "pin_weak": "{brand}፦ ሁሉም አንድ ያልሆኑ እና እንደ 1234 ያልሆኑ 4 አሃዞች ይምረጡ። PIN፣ የድሮ ፒን እና አዲሱን ይላኩ።",
        "pin_format": "{brand}፦ ፒን ለመቀየር PIN፣ የድሮ ፒንዎን እና አዲሱን ይላኩ፤ ለምሳሌ PIN 4821 7395።",
    },
}

FLAGS = {"en": {"low": "LOW", "normal": "normal", "high": "HIGH", "critical": "CRITICAL"},
         "am": {"low": "ዝቅተኛ", "normal": "መደበኛ", "high": "ከፍተኛ", "critical": "አሳሳቢ"}}


@dataclass
class Answer:
    reply: Optional[str]
    outcome: str
    command: Optional[str] = None
    user_id: Optional[str] = None


def _say(language: str, key: str, **values: Any) -> str:
    return T[language][key].format(brand=BRAND, **values)


def _max_segments() -> int:
    return max(1, sms_settings.number("SMS_REPLY_MAX_SEGMENTS"))


# --- sensitive results ---------------------------------------------------------------------

def _keyword_hit(text: Optional[str]) -> bool:
    if not text:
        return False
    lower = str(text).lower()
    for keyword in sms_settings.sensitive_keywords():
        if keyword.isascii():
            # The keyword must start a word ("mental", not "supplemental").
            if re.search(r"(?<![a-z0-9])" + re.escape(keyword), lower):
                return True
        elif keyword in lower:
            return True
    return False


def sensitive_item(item: Dict[str, Any]) -> bool:
    code = str(item.get("code") or "").strip().lower()
    return (bool(code) and code in sms_settings.sensitive_loinc()) or _keyword_hit(item.get("test"))


def sensitive_record(record: HospitalRecord, details: Dict[str, Any]) -> bool:
    if _keyword_hit(record.title):
        return True
    if record.category == "diagnosis":
        code = str(details.get("code") or "").strip().upper()
        if code and any(code.startswith(prefix) for prefix in sms_settings.sensitive_icd10()):
            return True
    return any(_keyword_hit(details.get(key)) for key in
               ("condition", "notes", "findings", "impression", "plan", "complaint", "description", "body_part",
                "modality"))


# --- parsing --------------------------------------------------------------------------------

def parse(text: str) -> Tuple[str, List[str]]:
    words = (text or "").strip().split()
    if not words:
        return HELP, []
    return ALIASES.get(words[0].upper(), HELP), words[1:]


def _day(value: datetime) -> str:
    return f"{ensure_aware(value).astimezone(ZONE):%d/%m/%Y}"


def _when(value: datetime) -> str:
    return f"{ensure_aware(value).astimezone(ZONE):%d/%m/%Y %H:%M}"


# --- answers --------------------------------------------------------------------------------

def _details(record: HospitalRecord) -> Dict[str, Any]:
    try:
        details = json.loads(record.details_json or "{}")
    except ValueError:
        return {}
    return details if isinstance(details, dict) else {}


def _records(session: Session, user_id: str, categories: Iterable[str]) -> List[HospitalRecord]:
    return list(session.scalars(select(HospitalRecord).where(
        HospitalRecord.user_id == user_id, HospitalRecord.category.in_(list(categories)),
        HospitalRecord.retracted_at.is_(None)).order_by(HospitalRecord.occurred_at.desc(), HospitalRecord.id)
        .limit(200)))


def _result_line(item: Dict[str, Any], date: str, language: str, short: bool = False) -> str:
    test = str(item.get("test") or "")
    if short and len(test) > 16:
        test = test[:15] + "."
    value = " ".join(str(item.get(k)) for k in ("value", "unit") if item.get(k) not in (None, ""))
    flag = FLAGS[language].get(item.get("flag") or "")
    return f"{date} {test}: {value}" + (f" ({flag})" if flag else "")


def answer_results(session: Session, user_id: str, language: str, page: int) -> Tuple[str, int]:
    """(reply, how many results were withheld as sensitive)."""
    items: List[Tuple[str, Optional[Dict[str, Any]]]] = []
    for record in _records(session, user_id, ("lab_result",)):
        details = _details(record)
        whole = sensitive_record(record, details)
        for item in details.get("items") or []:
            if isinstance(item, dict):
                items.append((_day(record.occurred_at), None if whole or sensitive_item(item) else item))
    if not items:
        return _say(language, "no_results"), 0
    per = max(1, sms_settings.number("SMS_RESULTS_PER_REPLY"))
    chunk = items[(page - 1) * per: page * per]
    if not chunk:
        return _say(language, "no_more_results"), 0
    more = _say(language, "more_results", page=page + 1) if page * per < len(items) else ""
    withheld = sum(1 for _d, item in chunk if item is None)
    for short in (False, True):
        lines = [_say(language, "results_head")]
        for date, item in chunk:
            lines.append(_say(language, "withheld", date=date) if item is None
                         else _result_line(item, date, language, short))
        if more:
            lines.append(more)
        text = "\n".join(lines)
        if sms_segments.segments(text) <= _max_segments():
            return text, withheld
    return sms_segments.cut(text, _max_segments()), withheld


def _conclusion(record: HospitalRecord, details: Dict[str, Any]) -> str:
    keys = {"imaging": ("impression", "findings"), "visit_note": ("plan", "findings", "complaint"),
            "diagnosis": ("condition", "notes"), "document": ("description",)}.get(record.category, ())
    for key in keys:
        if details.get(key):
            text = str(details[key])
            if record.category == "diagnosis" and details.get("status"):
                text = f"{text} ({details['status']})"
            return text
    return ""


def answer_report(session: Session, user_id: str, language: str, page: int) -> Tuple[str, int]:
    records = _records(session, user_id, REPORT_CATEGORIES)
    if not records:
        return _say(language, "no_reports"), 0
    if page > len(records):
        return _say(language, "no_more_reports"), 0
    record = records[page - 1]
    details = _details(record)
    more = _say(language, "more_reports", page=page + 1) if page < len(records) else ""
    if sensitive_record(record, details):
        return "\n".join(p for p in (_say(language, "report_withheld", date=_day(record.occurred_at)), more) if p), 1
    body = f"{BRAND} {_day(record.occurred_at)}: {record.title}"
    conclusion = _conclusion(record, details)
    if conclusion:
        body = f"{body}. {conclusion}"
    if not more:
        return sms_segments.cut(body, _max_segments()), 0
    # The pointer to older reports always shows: the report is shortened instead.
    room = _max_segments()
    text = f"{body}\n{more}"
    while sms_segments.segments(text) > room and len(body) > 40:
        body = body[:-10].rstrip()
        text = f"{body}...\n{more}"
    return sms_segments.cut(text, room), 0


def answer_appointments(session: Session, user_id: str, language: str) -> str:
    from dedan_platform.hospital_bookings import HospitalState

    now = utcnow()
    lines: List[str] = []
    appointments = session.scalars(select(Appointment).where(
        Appointment.user_id == user_id, Appointment.scheduled_at >= now, Appointment.cancelled_at.is_(None),
        Appointment.status.in_([EventStatus.SCHEDULED, EventStatus.CONFIRMED, EventStatus.RESCHEDULED]))
        .order_by(Appointment.scheduled_at).limit(10)).all()
    shown = 0
    for appointment in appointments:
        if appointment.hospital_id and appointment.hospital_state not in HospitalState.OPEN:
            continue  # waiting for payment, refused or ended: not a visit
        hospital = session.get(PartnerHospital, appointment.hospital_id) if appointment.hospital_id else None
        where = hospital.name if hospital is not None else (appointment.location or "")
        key = "appt" if where else "appt_nowhere"
        lines.append(_say(language, key, when=_when(appointment.scheduled_at), where=where))
        shown += 1
        if shown == 2:
            break
    today = datetime.now(ZONE).date().isoformat()
    for follow_up in session.scalars(select(FollowUp).where(
            FollowUp.user_id == user_id, FollowUp.cancelled_at.is_(None), FollowUp.follow_up_on >= today)
            .order_by(FollowUp.follow_up_on).limit(2)):
        day = datetime.strptime(follow_up.follow_up_on, "%Y-%m-%d")
        lines.append(_say(language, "follow_up", when=f"{day:%d/%m/%Y}", where=follow_up.hospital_name))
    if not lines:
        return _say(language, "no_appt")
    return sms_segments.fit_lines([_say(language, "appt_head")] + lines, _max_segments())


def answer_prescriptions(session: Session, user_id: str, language: str) -> str:
    from dedan_platform import prescriptions

    lines: List[str] = []
    for rx in session.scalars(select(Prescription).where(
            Prescription.user_id == user_id, Prescription.active_code.is_not(None))
            .order_by(Prescription.created_at.desc()).limit(10)):
        record = session.get(HospitalRecord, rx.record_id)
        if record is None or prescriptions.current_status(rx, record) != prescriptions.OPEN:
            continue
        lines.append(_say(language, "rx", code=rx.code, until=_day(rx.expires_at), hospital=record.hospital_name))
        if len(lines) == 3:
            break
    if not lines:
        return _say(language, "no_rx")
    return sms_segments.fit_lines([_say(language, "rx_head")] + lines, _max_segments())


# --- one text -------------------------------------------------------------------------------

def _owner(session: Session, phone: str) -> Optional[User]:
    user = session.scalar(select(User).join(Profile, Profile.user_id == User.id).where(
        Profile.phone == phone, Profile.phone_verified_at.is_not(None)).limit(1))
    if user is None or not user.is_active or user.suspended_at is not None:
        return None
    return user


def _language(session: Session, user_id: str) -> str:
    language = session.scalar(select(Preferences.language).where(Preferences.user_id == user_id))
    return language if language in ("am", "en") else "en"


def _page(args: List[str]) -> Tuple[int, List[str]]:
    if len(args) >= 2 and args[0].isascii() and args[0].isdigit() and len(args[0]) <= 2:
        return min(max(1, int(args[0])), MAX_PAGE), args[1:]
    return 1, args


def _with_pin(session: Session, user: User, language: str, command: str, args: List[str]) -> Answer:
    """A command that needs the PIN."""
    page, rest = _page(args) if command in (RESULT, REPORT) else (1, args)
    pin = rest[-1] if rest else ""
    if len(rest) != 1 or not sms_pin.is_pin(pin):
        return Answer(_say(language, "format", command=command), "bad_format", command, user.id)
    check = sms_pin.check(session, user.id, pin)
    if check.outcome == "no_pin":
        return Answer(_say(language, "help_no_pin"), "no_pin", command, user.id)
    if check.outcome == "locked":
        until = f"{check.locked_until.astimezone(ZONE):%H:%M}"
        key = "locked_now" if check.just_locked else "locked"
        return Answer(_say(language, key, until=until), "pin_locked_now" if check.just_locked else "pin_locked",
                      command, user.id)
    if check.outcome == "wrong":
        return Answer(_say(language, "wrong_pin", left=check.attempts_left), "wrong_pin", command, user.id)
    withheld = 0
    if command == CARD:
        reply = _say(language, "card", card=user.dedan_user_id)
    elif command == APPT:
        reply = answer_appointments(session, user.id, language)
    elif command == RESULT:
        reply, withheld = answer_results(session, user.id, language, page)
    elif command == REPORT:
        reply, withheld = answer_report(session, user.id, language, page)
    else:
        reply = answer_prescriptions(session, user.id, language)
    return Answer(reply, "ok_withheld" if withheld else "ok", command, user.id)


def _change_pin(session: Session, user: User, language: str, args: List[str]) -> Answer:
    if len(args) != 2 or not (sms_pin.is_pin(args[0]) and sms_pin.is_pin(args[1])):
        return Answer(_say(language, "pin_format"), "bad_format", PIN, user.id)
    check = sms_pin.check(session, user.id, args[0])
    if check.outcome == "no_pin":
        return Answer(_say(language, "help_no_pin"), "no_pin", PIN, user.id)
    if check.outcome == "locked":
        until = f"{check.locked_until.astimezone(ZONE):%H:%M}"
        return Answer(_say(language, "locked_now" if check.just_locked else "locked", until=until),
                      "pin_locked_now" if check.just_locked else "pin_locked", PIN, user.id)
    if check.outcome == "wrong":
        return Answer(_say(language, "wrong_pin", left=check.attempts_left), "wrong_pin", PIN, user.id)
    if not sms_pin.acceptable(args[1]):
        return Answer(_say(language, "pin_weak"), "pin_weak", PIN, user.id)
    sms_pin.set_pin(session, user.id, args[1])
    return Answer(_say(language, "pin_changed"), "pin_changed", PIN, user.id)


def _record(provider: str, message_id: Optional[str], phone_masked: str) -> Optional[str]:
    """Audit the text as received; None when this provider message was seen already."""
    try:
        with session_scope() as session:
            row = SmsInboundMessage(provider=provider[:24], provider_message_id=(message_id or None) and
                                    message_id[:100], phone_masked=phone_masked, outcome="received")
            session.add(row)
            session.flush()
            return row.id
    except IntegrityError:
        return None


def _finish(audit_id: str, answer: Answer) -> Answer:
    with session_scope() as session:
        row = session.get(SmsInboundMessage, audit_id)
        if row is not None:
            row.outcome, row.command, row.user_id = answer.outcome, answer.command, answer.user_id
    logger.info("sms_inbound command=%s outcome=%s user_id=%s", answer.command, answer.outcome, answer.user_id)
    return answer


def handle(provider: str, message_id: Optional[str], sender: str, text: str) -> Answer:
    """Answer one received text (``Answer.reply`` None: send nothing)."""
    phone = normalise_ethiopian_mobile(sender)
    audit_id = _record(provider, message_id, mask(phone or str(sender or "")[:20]))
    if audit_id is None:
        return Answer(None, "duplicate")
    if phone is None:
        return _finish(audit_id, Answer(None, "invalid_sender"))
    try:
        throttle.begin({f"sms-in:{phone}": max(1, sms_settings.number("SMS_INBOUND_MAX_PER_PHONE_PER_HOUR")),
                        "sms-in:all": max(1, sms_settings.number("SMS_INBOUND_MAX_PER_HOUR"))})
    except throttle.Limited:
        return _finish(audit_id, Answer(None, "rate_limited"))
    command, args = parse(text)
    with session_scope() as session:
        user = _owner(session, phone)
        if user is None:
            answer = Answer(None, "unknown_sender", command)
        elif command == HELP:
            language = _language(session, user.id)
            answer = Answer(_say(language, "help" if sms_pin.has_pin(session, user.id) else "help_no_pin"),
                            "help", HELP, user.id)
        elif command == PIN:
            answer = _change_pin(session, user, _language(session, user.id), args)
        else:
            answer = _with_pin(session, user, _language(session, user.id), command, args)
    if answer.outcome == "unknown_sender":
        # One "not registered" reply a day at most (it names no account).
        try:
            throttle.begin({f"sms-in-unknown:{phone}": 1}, window=timedelta(days=1))
            answer.reply = _say("am", "unknown_sender") + "\n" + _say("en", "unknown_sender")
        except throttle.Limited:
            answer.reply = None
    if answer.reply:
        answer.reply = sms_segments.cut(answer.reply, _max_segments())
    return _finish(audit_id, answer)
