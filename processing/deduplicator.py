from __future__ import annotations

from processing.verifier import canonicalize_url


def same_notice(url_a: str | None, hash_a: str | None, url_b: str | None, hash_b: str | None) -> bool:
    if hash_a and hash_b and hash_a == hash_b:
        return True
    return bool(url_a and url_b and canonicalize_url(url_a) == canonicalize_url(url_b) and hash_a == hash_b)


def is_changed_revision(previous_hash: str | None, current_hash: str | None) -> bool:
    return bool(previous_hash and current_hash and previous_hash != current_hash)

