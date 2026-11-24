# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Verdict rules for the licence ledger (``compliance/licence-policy.json``).

``allow`` is given only when *every* licence recognised for an item is
on the allow-list: then the verdict holds whether the licences combine
as a choice or cumulatively.  Everything else is ``needs-review``; a
tool never writes ``reject`` or upgrades a row on its own, because both
are decisions for a person.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

VERDICTS = ("allow", "needs-review", "reject")


class PolicyError(ValueError):
    """The policy file is malformed."""


@dataclass(frozen=True)
class Policy:
    allow: frozenset
    ask_first_prefixes: Tuple[str, ...]
    obligations: Dict[str, str]

    def is_allowed(self, spdx: str) -> bool:
        return spdx in self.allow

    def is_ask_first(self, spdx: str) -> bool:
        return spdx.startswith(self.ask_first_prefixes)

    def verdict(self, licences: Sequence[str]) -> Tuple[str, str]:
        """Return ``(verdict, reason)`` for the licences recognised for one item."""
        licences = list(dict.fromkeys(licences))
        if not licences:
            return ("needs-review",
                    "no licence text recognised; inspect by hand, reject if none exists")
        allowed = [item for item in licences if self.is_allowed(item)]
        ask = [item for item in licences if self.is_ask_first(item)]
        other = [item for item in licences if item not in allowed and item not in ask]
        if len(allowed) == len(licences):
            return ("allow", "every recognised licence is pre-approved")
        parts: List[str] = []
        if ask:
            parts.append("ask first: " + ", ".join(ask))
        if other:
            parts.append("not pre-approved: " + ", ".join(other))
        if allowed:
            parts.append("pre-approved alternatives/components: " + ", ".join(allowed)
                         + " (decide whether this is a choice or cumulative)")
        return ("needs-review", "; ".join(parts))

    def obligations_for(self, licences: Sequence[str]) -> str:
        texts = []
        for item in dict.fromkeys(licences):
            texts.append(f"{item}: {self.obligations.get(item, 'UNKNOWN - read the licence text')}")
        return " | ".join(texts)


def load_policy(path: Path) -> Policy:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        allow = data["allow"]
        prefixes = data["ask_first_prefixes"]
        obligations = data["obligations"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PolicyError(f"{path}: {exc}") from exc
    if not (isinstance(allow, list) and all(isinstance(item, str) and item for item in allow)):
        raise PolicyError("allow must be a list of SPDX identifiers")
    if not (isinstance(prefixes, list) and all(isinstance(i, str) and i for i in prefixes)):
        raise PolicyError("ask_first_prefixes must be a list of non-empty strings")
    if not isinstance(obligations, dict):
        raise PolicyError("obligations must be an object")
    clash = [item for item in allow if item.startswith(tuple(prefixes))]
    if clash:
        raise PolicyError(f"identifier is both allowed and ask-first: {', '.join(clash)}")
    return Policy(frozenset(allow), tuple(prefixes), dict(obligations))
