"""Context ACL: administrative memory is readable only by an admin role INSIDE an admin channel."""
import os
from dataclasses import dataclass
from typing import Optional

ADMIN_TOPIC_HINTS = (
    "سجل الإدارة", "سجلات الإدارة", "قرارات الإدارة", "اجتماع الإدارة", "خاص بالإدارة",
    "admin log", "admin memory", "mod log", "staff notes", "إدارة فقط",
)


def _id_set(name: str) -> set:
    out = set()
    for part in (os.getenv(name, "") or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


ADMIN_ROLE_IDS = _id_set("MALAK_ADMIN_ROLE_IDS")
ADMIN_CHANNEL_IDS = _id_set("MALAK_ADMIN_CHANNEL_IDS")
OWNER_ID = int((os.getenv("MALAK_OWNER_ID") or "0").strip() or 0) if (os.getenv("MALAK_OWNER_ID") or "").strip().isdigit() else 0


class AclError(PermissionError):
    pass


@dataclass(frozen=True)
class Context:
    scope: str
    guild_id: int
    channel_id: int

    @property
    def is_admin(self) -> bool:
        return self.scope == "admin"


def is_admin_member(member) -> bool:
    if member is None:
        return False
    if OWNER_ID and getattr(member, "id", 0) == OWNER_ID:
        return True
    role_ids = {getattr(r, "id", 0) for r in getattr(member, "roles", []) or []}
    if ADMIN_ROLE_IDS and (role_ids & ADMIN_ROLE_IDS):
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(getattr(perms, "administrator", False))


def resolve_context(member, channel) -> Context:
    guild = getattr(channel, "guild", None)
    gid = getattr(guild, "id", 0) or 0
    cid = getattr(channel, "id", 0) or 0
    admin_channel = bool(ADMIN_CHANNEL_IDS) and cid in ADMIN_CHANNEL_IDS
    return Context("admin" if (admin_channel and is_admin_member(member)) else "public", gid, cid)


def require_admin_context(member, channel) -> Context:
    ctx = resolve_context(member, channel)
    if not ctx.is_admin:
        raise AclError("admin context refused: role or channel not authorized")
    return ctx


def is_admin_query(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in ADMIN_TOPIC_HINTS)


def public_refusal(question: str) -> Optional[str]:
    if not is_admin_query(question):
        return None
    return "هذا الكلام بين الإدارة، ما ينقال هنا."
