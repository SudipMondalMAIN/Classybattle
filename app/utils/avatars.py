"""
Predefined avatar catalogue. Users select an avatar_id from this fixed
list instead of uploading a custom profile photo.
"""

PREDEFINED_AVATARS: list[str] = [
    "avatar_01",
    "avatar_02",
    "avatar_03",
    "avatar_04",
    "avatar_05",
    "avatar_06",
    "avatar_07",
    "avatar_08",
    "avatar_09",
    "avatar_10",
]


def is_valid_avatar(avatar_id: str) -> bool:
    return avatar_id in PREDEFINED_AVATARS
