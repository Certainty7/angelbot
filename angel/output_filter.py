"""Deterministic post-filter for model-generated text (v1).

This is not an authorization layer and it cannot make the model truthful. It catches four
cheap, high-signal classes before the text reaches Discord:

  * mass mentions (`@everyone` / `@here`), which the client also disables at the API layer;
  * token-shaped secrets;
  * leftover control tags;
  * a first-person moderation claim when no action actually executed.

Only the reason is logged, never the text, so private message content does not enter logs.
"""
import re

from .config import logger


def redact_secrets(text: str) -> str:
  """Redact token-shaped strings; used before a summary or log line is shown."""
  out = text or ""
  for pattern in _SECRETS:
    out = pattern.sub("[محجوب]", out)
  return out

_MASS = re.compile(r"@(everyone|here)\b", re.IGNORECASE)
# A model can emit a role mention directly; neutralise it even if the API layer also
# disables role pings.
_ROLE_MENTION = re.compile(r"<@&\d+>")

_SECRETS = (
    # Discord bot token: id.timestamp.hmac
    re.compile(r"\b[A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{25,40}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*"),
    # KEY=value lines pasted from a .env file.
    re.compile(r"(?i)\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_?KEY)\s*=\s*\S+"),
)

_TAGS = re.compile(
    r"\[\s*(?:EXEC|BAN|KICK|TIMEOUT|UNTIMEOUT|PURGE|UNBAN|DELETE_CHANNEL|LOCK|UNLOCK|"
    r"HIDE|UNHIDE|SLOWMODE|ADD_ROLE|REMOVE_ROLE|CREATE_ROLE|NICKNAME|SET_TOPIC|"
    r"CREATE_TEXT|CREATE_VOICE|CLONE_CHANNEL|RENAME_CHANNEL|SET_MODLOG|GUARD_MODE|PIN_FACT)"
    r"\b[^\]]*\]",
    re.IGNORECASE,
)

# First-person past-tense moderation claims. Deliberately narrow: only phrases that assert
# an action on a member/channel, not ordinary uses such as "مسحت الغبار".
_CLAIM = re.compile(
    r"(?:^|[\s،.!؟])(?:حظرت|طردت|كتمت|عزلت|ألغيت\s+الحظر|الغيت\s+الحظر|"
    r"رفعت\s+الحظر|مسحت\s+(?:ال)?رسائل|حذفت\s+(?:ال)?رسائل|قفلت\s+(?:ال)?قناة|"
    r"فتحت\s+(?:ال)?قناة|أضفت\s+(?:ال)?رتبة|اضفت\s+(?:ال)?رتبة)"
)


def filter_outgoing(text: str, action_status: str = "none") -> str:
  """Return the text with cheap unsafe classes removed or corrected.

  action_status is the aggregate result of execute_ai_inferred_action for this turn:
  executed / queued / blocked / failed / none.
  """
  if not text:
    return text

  reasons = []
  out = _MASS.sub(lambda m: m.group(1), text)
  if out != text:
    reasons.append("mass-mention")

  replaced = _ROLE_MENTION.sub("@role", out)
  if replaced != out:
    out = replaced
    reasons.append("role-mention")

  for pattern in _SECRETS:
    replaced = pattern.sub("[محجوب]", out)
    if replaced != out:
      out = replaced
      reasons.append("secret-shaped")

  replaced = _TAGS.sub("", out)
  if replaced != out:
    out = replaced
    reasons.append("control-tag")

  if action_status != "executed" and _CLAIM.search(out):
    if action_status == "queued":
      out = "⚠️ الإجراء جاهز لكنه **لم يُنفَّذ بعد** — اكتب «تأكيد» خلال 60 ثانية."
    else:
      out = "ما نفّذت أي إجراء إداري الآن. لو تقصد حظر/طرد/مسح، اطلبه صراحةً."
    reasons.append(f"claim-without-exec({action_status})")

  if reasons:
    logger.warning("output-filter reasons=%s", ",".join(sorted(set(reasons))))
  return out
