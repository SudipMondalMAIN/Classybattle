"""
Predefined avatar catalogue. Users select an avatar_id from this fixed
list instead of uploading a custom profile photo.

Must stay in sync with:
- assets/avatars/avatar_1.png ... avatar_6.png in the Flutter app
- VALID_AVATAR_IDS in app/schemas/user.py
"""

PREDEFINED_AVATARS: list[str] = [
    "avatar_1",
    "avatar_2",
    "avatar_3",
    "avatar_4",
    "avatar_5",
    "avatar_6",
]


def is_valid_avatar(avatar_id: str) -> bool:
    return avatar_id in PREDEFINED_AVATARS
