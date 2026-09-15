"""Canonical job URL — the deterministic dedup key.

The SAME posting reaches us from several sources: a Greenhouse board, a LinkedIn alert email, a
Job Bank feed, an Apify Indeed scrape. Each decorates the URL differently (tracking params, a
trailing slash, a host alias, an `#apply` fragment). Dedup on *company + title* instead would be
worse, not better: two genuinely different reqs at one company routinely share a title, and
collapsing them loses one of them silently.

So: normalize hard, and treat the result as identity.

Deliberately NOT canonicalized: the path's case. ATS job ids are case-sensitive tokens
(`jobs.ashbyhq.com/acme/AbC123` ≠ `.../abc123`), so lowercasing the path can merge two real
postings into one. Only the host is lowercased, which is safe — DNS is case-insensitive.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Params that carry no identity — campaign, referrer and session noise.
_STRIP_PREFIXES = ("utm_", "pk_", "mc_", "hsa_", "ic_")
_STRIP_EXACT = frozenset({
    "gh_src", "gh_jid_src", "src", "source", "ref", "referrer", "referer",
    "trk", "trackingid", "trk_ref", "originalsubdomain", "position", "pagenum",
    "fbclid", "gclid", "msclkid", "igshid", "mkt_tok", "lipi", "licu",
    "sessionid", "session_id", "jsessionid", "_ga", "_gl", "recommended",
})
# Params that ARE identity for some ATSes — never strip these.
_KEEP = frozenset({"gh_jid", "jid", "jobid", "job_id", "id", "vjk", "jk", "currentjobid", "postingid"})

# A leading "<scheme>:" — used to tell "declares a scheme" from "bare host".
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
# A plausible hostname: dot-separated labels, or bare "localhost"-style (rejected below anyway).
_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9\-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9\-]*[a-z0-9])?)+$")

_HOST_ALIAS = {
    "www.linkedin.com": "linkedin.com",
    "ca.indeed.com": "indeed.com",
    "www.indeed.com": "indeed.com",
    "boards.greenhouse.io": "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io": "job-boards.greenhouse.io",
    "www.jobbank.gc.ca": "jobbank.gc.ca",
}


def canonical_url(raw: str) -> str:
    """Normalize a posting URL into its identity form. Returns '' for anything unusable."""
    if not raw or not isinstance(raw, str):
        return ""
    url = raw.strip()
    if not url or any(ch.isspace() for ch in url):
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif _SCHEME.match(url):
        # It declares a scheme. Only http(s) may proceed — prepending "https://" to
        # "javascript:alert(1)" would launder a non-web scheme into a valid-looking URL.
        if not url.lower().startswith(("http://", "https://")):
            return ""
    else:
        url = "https://" + url

    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return ""

    host = parts.hostname or ""
    host = host.lower().rstrip(".")
    if host.startswith("www.") and host not in _HOST_ALIAS:
        host = host[4:]
    host = _HOST_ALIAS.get(host, host)
    # A posting lives on a real public host. Reject anything that isn't one, so a malformed
    # string can never become a stored "listing" that something later tries to open.
    if not _HOSTNAME.match(host):
        return ""

    # Path: keep case (ATS ids are case-sensitive), drop a trailing slash, collapse doubles.
    path = parts.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    kept = []
    for k, v in parse_qsl(parts.query, keep_blank_values=False):
        lk = k.lower()
        if lk in _KEEP:
            kept.append((k, v))
            continue
        if lk in _STRIP_EXACT or lk.startswith(_STRIP_PREFIXES):
            continue
        kept.append((k, v))
    # Stable order so ?a=1&b=2 and ?b=2&a=1 are one posting.
    query = urlencode(sorted(kept))

    # Fragments never identify a posting (#apply, #job-details).
    return urlunsplit(("https", host, path, query, ""))


def same_posting(a: str, b: str) -> bool:
    ca, cb = canonical_url(a), canonical_url(b)
    return bool(ca) and ca == cb
