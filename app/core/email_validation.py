"""
Signup email domain allowlist.

Bot-driven signup farming (fake accounts created in bulk, e.g. to abuse
referral rewards or promo credits) relies on an unlimited, disposable
supply of inboxes to receive the signup OTP. A blocklist of known
throwaway domains is a losing game -- bots simply rotate to a new,
not-yet-blocked domain.

Instead, this takes the opposite (allowlist) approach: signup is only
permitted from a short list of well-known, real email providers. Anything
not on this list -- disposable domains, obscure/custom domains, freshly
registered proxy domains like `uberip.com`, etc. -- is rejected outright.

This is deliberately strict. It WILL reject legitimate users on smaller
or work-email providers not in the list below. Extend
ALLOWED_EMAIL_DOMAINS as needed for real providers you want to support.
"""
from __future__ import annotations

# Only signups from these email domains are accepted. Keep this list to
# well-known, large mailbox providers that are hard for a bot to mass
# generate throwaway inboxes on.
ALLOWED_EMAIL_DOMAINS: set[str] = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "zohomail.com",
    "zoho.com",
    "proton.me",
    "protonmail.com",
}


def is_allowed_email_domain(email: str) -> bool:
    """True if `email`'s domain is on the signup allowlist."""
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in ALLOWED_EMAIL_DOMAINS