"""Streamlit renders Markdown in headers, captions and messages. Text a customer
typed (their name) must be shown literally, so a name can't turn into a link,
a heading, an image or an emoji shortcode on screen."""

import re

_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~:$])")


def escape(text: str) -> str:
    return _SPECIAL.sub(r"\\\1", text)
