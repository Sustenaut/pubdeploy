"""The DNS names and record types the dns.site check may ask a resolver
about: absolute, lower case, labels of letters, digits, hyphens and
underscores; types in capitals. Anything else stops the check. After
pubkit's dns.NAME, checked and checked_type."""

from __future__ import annotations

import re
import sys

NAME = re.compile(r"(?:[a-z0-9_][a-z0-9_-]{0,62}\.)+")
TYPE = re.compile(r"[A-Z][A-Z0-9]{0,9}")
LONGEST = 254  # an absolute name's length, its final dot included


def checked(name: str) -> str:
    if not NAME.fullmatch(name) or len(name) > LONGEST:
        sys.exit(f"pubdeploy: {name!r} is not a DNS name the deploy walk asks about")
    return name


def checked_type(rtype: str) -> str:
    if not TYPE.fullmatch(rtype):
        sys.exit(f"pubdeploy: {rtype!r} is not a DNS record type, such as A or MX")
    return rtype
