"""Portable public-metadata reader; generated from the reviewed Confluencia engine."""
from pathlib import Path

from datetime import datetime, timezone, timedelta

import argparse

import hashlib

import json

import os

import re

import tempfile

import urllib.error

import urllib.parse

import urllib.request

from email.utils import parsedate_to_datetime

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = "official-public-collection-cache-v1"

MAX_BYTES, MAX_PAGES, MAX_REQUESTS = 2_000_000, 4, 24

MIN_INTERVAL = 86400

TARGETS = {
    "github": ("github", "repository", "rodrix91", "https://api.github.com/users/rodrix91/repos?type=owner&per_page=100&page=1"),
    "gitlab": ("gitlab", "repository", "rodripn91", "https://gitlab.com/api/v4/users/rodripn91/projects?visibility=public&per_page=100&page=1"),
    "models": ("huggingface", "model", "Hugdrigo", "https://huggingface.co/api/models?author=Hugdrigo&limit=100"),
    "datasets": ("huggingface", "dataset", "Hugdrigo", "https://huggingface.co/api/datasets?author=Hugdrigo&limit=100"),
    "spaces": ("huggingface", "space", "Hugdrigo", "https://huggingface.co/api/spaces?author=Hugdrigo&limit=100"),
}

class Invalid(Exception):
    pass

def require(value, code="invalid_response"):
    if not value:
        raise Invalid(code)

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()

def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()

def stamp(now):
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def date(value):
    require(isinstance(value, str), "invalid_timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.tzinfo is not None, "invalid_timestamp")
        return result
    except ValueError as error:
        raise Invalid("invalid_timestamp") from error

def safe_url(key, url):
    """Only the same collection and owner; cursor/page never grant arbitrary GETs."""
    require(isinstance(url, str) and len(url) <= 4096, "unsafe_pagination")
    base, current = urllib.parse.urlsplit(TARGETS[key][3]), urllib.parse.urlsplit(url)
    require(current.scheme == "https" and current.netloc == base.netloc and current.path == base.path
            and not current.fragment and not current.username and not current.password, "unsafe_pagination")
    params = urllib.parse.parse_qs(current.query, keep_blank_values=True)
    original = urllib.parse.parse_qs(base.query)
    require(all(len(v) == 1 for v in params.values()), "unsafe_pagination")
    require(set(params) <= set(original) | {"cursor", "page"}, "unsafe_pagination")
    require(all(params.get(k) == v for k, v in original.items() if k != "page"), "unsafe_pagination")
    if "page" in params:
        require(re.fullmatch(r"[1-9][0-9]{0,5}", params["page"][0]), "unsafe_pagination")
    if "cursor" in params:
        require(len(params["cursor"][0]) <= 2048, "unsafe_pagination")
    return url

def next_url(key, url, headers):
    links = []
    for part in headers.get("link", "").split(","):
        if re.search(r'\brel\s*=\s*[\"\x27]?next\b', part):
            match = re.search(r"<([^>]+)>", part)
            require(match, "invalid_pagination")
            links.append(safe_url(key, urllib.parse.urljoin(url, match.group(1))))
    require(len(links) <= 1, "invalid_pagination")
    number = headers.get("x-next-page")
    if number:
        require(re.fullmatch(r"[1-9][0-9]{0,5}", number), "invalid_pagination")
        parsed = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qs(parsed.query)
        params["page"] = [number]
        following = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(params, doseq=True)))
        safe_url(key, following)
        if links:
            require(urllib.parse.parse_qs(urllib.parse.urlsplit(links[0]).query) == params, "invalid_pagination")
        else:
            links.append(following)
    return links[0] if links else None

def normalize(key, rows):
    require(isinstance(rows, list) and len(rows) <= 100, "invalid_collection")
    platform, kind, owner, _ = TARGETS[key]
    result = []
    for row in rows:
        require(isinstance(row, dict), "invalid_record")
        if platform == "github":
            require(row.get("private") is False and (row.get("owner") or {}).get("login", "").casefold() == owner.casefold(), "visibility_or_owner")
            name, ident = row.get("full_name"), row.get("id")
            source_url, updated = row.get("html_url"), row.get("pushed_at")
            fork, archived = row.get("fork"), row.get("archived")
        elif platform == "gitlab":
            require(row.get("visibility") == "public" and (row.get("namespace") or {}).get("full_path") == owner, "visibility_or_owner")
            name, ident = row.get("path_with_namespace"), row.get("id")
            source_url, updated = row.get("web_url"), row.get("last_activity_at")
            fork, archived = None, row.get("archived")
        else:
            require(row.get("private") is False, "visibility_or_owner")
            name, ident = row.get("id"), row.get("_id")
            source_url = "https://huggingface.co/" + ("spaces/" if kind == "space" else "datasets/" if kind == "dataset" else "") + str(name)
            updated = row.get("lastModified")
            fork, archived = None, None
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name)
                and name.split("/")[0].casefold() == owner.casefold(), "visibility_or_owner")
        require((isinstance(ident, int) and not isinstance(ident, bool) and ident > 0) if platform != "huggingface"
                else isinstance(ident, str) and re.fullmatch(r"[a-f0-9]{24}", ident), "invalid_remote_id")
        expected_url = ("https://github.com/" if platform == "github" else "https://gitlab.com/" if platform == "gitlab" else
                        "https://huggingface.co/" + ("spaces/" if kind == "space" else "datasets/" if kind == "dataset" else "")) + name
        require(source_url == expected_url, "invalid_resource_url")
        require(fork is None or isinstance(fork, bool), "invalid_record")
        require(archived is None or isinstance(archived, bool), "invalid_record")
        if updated is not None:
            date(updated)
        result.append(dict(remoteId=str(ident), name=name, url=source_url, lastActivity=updated, fork=fork, archived=archived))
    require(len({r["remoteId"] for r in result}) == len(result) and len({r["name"].casefold() for r in result}) == len(result), "duplicate_identity")
    return result

def validate_records(key, rows):
    require(isinstance(rows, list), "invalid_cache")
    require(len({r.get("remoteId") for r in rows}) == len(rows), "invalid_cache")
    require(len({r.get("name", "").casefold() for r in rows}) == len(rows), "invalid_cache")
    platform, kind, owner, _ = TARGETS[key]
    for row in rows:
        require(set(row) == {"remoteId", "name", "url", "lastActivity", "fork", "archived"}, "invalid_cache")
        # Reuse the remote-response validator; cached data does not bypass policy.
        if platform == "github":
            raw = dict(id=int(row["remoteId"]), full_name=row["name"], html_url=row["url"], private=False,
                       owner={"login":owner}, pushed_at=row["lastActivity"], fork=row["fork"], archived=row["archived"])
        elif platform == "gitlab":
            raw = dict(id=int(row["remoteId"]), path_with_namespace=row["name"], web_url=row["url"], visibility="public",
                       namespace={"full_path":owner}, last_activity_at=row["lastActivity"], archived=row["archived"])
        else:
            raw = dict(_id=row["remoteId"], id=row["name"], private=False, lastModified=row["lastActivity"])
        require(normalize(key, [raw]) == [row], "invalid_cache")

def validate_good(key, good):
    require(set(good) == {"observedAt", "records", "pages", "sha256"}, "invalid_cache")
    # The historical snapshot has day precision only; do not invent a capture hour.
    if isinstance(good["observedAt"], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", good["observedAt"]):
        try:
            datetime.strptime(good["observedAt"], "%Y-%m-%d")
        except ValueError as error:
            raise Invalid("invalid_timestamp") from error
    else:
        date(good["observedAt"])
    validate_records(key, good["records"])
    require(good["sha256"] == digest(good["records"]), "cache_digest_mismatch")
    require(isinstance(good["pages"], list) and len(good["pages"]) <= MAX_PAGES, "invalid_cache")
    combined, expected = [], TARGETS[key][3]
    for page in good["pages"]:
        require(set(page) == {"url", "next", "etag", "lastModified", "records", "bodySha256"}, "invalid_cache")
        require(page["url"] == expected, "invalid_cache")
        safe_url(key, page["url"])
        if page["next"]:
            safe_url(key, page["next"])
        for h in ["etag", "lastModified"]:
            require(page[h] is None or isinstance(page[h], str) and len(page[h]) <= 512 and "\r" not in page[h] and "\n" not in page[h], "invalid_cache")
        require(isinstance(page["bodySha256"], str) and re.fullmatch(r"[a-f0-9]{64}", page["bodySha256"]), "invalid_cache")
        validate_records(key, page["records"])
        combined.extend(page["records"])
        expected = page["next"]
    if good["pages"]:
        require(expected is None and sorted(combined, key=lambda r:r["remoteId"]) == good["records"], "invalid_cache")

def validate_state(state):
    require(set(state) == {"schema", "collections"} and state["schema"] == SCHEMA
            and set(state["collections"]) == set(TARGETS), "invalid_cache")
    for key, entry in state["collections"].items():
        require(set(entry) == {"status", "lastAttemptAt", "lastValidatedAt", "lastSuccessfulFetchAt", "backoffUntil", "failure", "lastGood", "pending"}, "invalid_cache")
        require(entry["status"] in {"historical", "fresh", "unchanged", "stale", "review_required"}, "invalid_cache")
        for field in ["lastAttemptAt", "lastValidatedAt", "lastSuccessfulFetchAt", "backoffUntil"]:
            if entry[field] is not None:
                date(entry[field])
        validate_good(key, entry["lastGood"])
        if entry["pending"] is not None:
            validate_good(key, entry["pending"])
        if entry["failure"] is not None:
            require(set(entry["failure"]) == {"code", "httpStatus"} and re.fullmatch(r"[a-z_]+", entry["failure"]["code"])
                    and (entry["failure"]["httpStatus"] is None or isinstance(entry["failure"]["httpStatus"], int)), "invalid_cache")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Invalid("redirect_refused")

def fetch_public(url, headers):
    req = urllib.request.Request(url, headers={"Accept":"application/json", "User-Agent":"Confluencia-public-cache/1.0", **headers}, method="GET")
    try:
        response = urllib.request.build_opener(NoRedirect()).open(req, timeout=8)
    except urllib.error.HTTPError as error:
        # Error bodies may contain private diagnostics; never persist them.
        with error:
            return error.code, {k.lower():v for k,v in error.headers.items()}, b""
    with response:
        body = response.read(MAX_BYTES + 1)
        require(len(body) <= MAX_BYTES, "response_too_large")
        return response.status, {k.lower():v for k,v in response.headers.items()}, body

def backoff(now, headers):
    raw = headers.get("retry-after", "")
    until = now + timedelta(hours=1)
    if raw.isdigit():
        # Do not shorten a provider's long retry interval or sleep in the runner.
        requested = datetime.max.replace(tzinfo=timezone.utc) if len(raw) > 8 else now + timedelta(seconds=int(raw))
        until = max(until, requested)
    elif raw:
        try:
            requested = parsedate_to_datetime(raw)
            if requested.tzinfo is not None:
                until = max(until, requested)
        except (ValueError, TypeError, OverflowError):
            pass
    reset = headers.get("x-ratelimit-reset", "")
    if reset.isdigit() and len(reset) <= 10:
        until = max(until, datetime.fromtimestamp(int(reset), timezone.utc))
    return stamp(until)

def refresh(state, now, fetch=fetch_public, force=False):
    validate_state(state)
    # Copy before modification so caller and historical seed remain unchanged.
    result = json.loads(json.dumps(state))
    report = dict(checkedAt=stamp(now), scope="public_collection_metadata_candidates_only", requests=0, collections={},
                  authenticatedRequests=False, published=False, scheduled=False, externalCodeExecuted=False)
    for key, entry in result["collections"].items():
        if entry["backoffUntil"] and now < date(entry["backoffUntil"]):
            report["collections"][key] = dict(action="backoff", status=entry["status"])
            continue
        if not force and entry["lastAttemptAt"] and (now - date(entry["lastAttemptAt"])).total_seconds() < MIN_INTERVAL:
            report["collections"][key] = dict(action="cached", status=entry["status"])
            continue
        entry["lastAttemptAt"] = stamp(now)
        cached_pages = {p["url"]:p for p in entry["lastGood"]["pages"]}
        pages, records, seen, statuses = [], [], set(), []
        url, failure_status = TARGETS[key][3], None
        try:
            while url:
                safe_url(key, url)
                require(url not in seen and len(pages) < MAX_PAGES, "pagination_budget")
                require(report["requests"] < MAX_REQUESTS, "request_budget")
                seen.add(url)
                previous = cached_pages.get(url)
                conditional = {}
                if previous and previous["etag"]:
                    conditional["If-None-Match"] = previous["etag"]
                elif previous and previous["lastModified"]:
                    conditional["If-Modified-Since"] = previous["lastModified"]
                report["requests"] += 1
                status, headers, body = fetch(url, conditional)
                failure_status = status
                statuses.append(status)
                if status == 304:
                    require(previous is not None and bool(conditional), "unexpected_not_modified")
                    page = json.loads(json.dumps(previous))
                else:
                    if status in (403, 429):
                        entry["backoffUntil"] = backoff(now, headers)
                    require(status == 200, "http_failure")
                    require(len(body) <= MAX_BYTES and "json" in headers.get("content-type", "").lower(), "invalid_content_type")
                    try:
                        rows = json.loads(body)
                    except (ValueError, UnicodeError) as error:
                        raise Invalid("invalid_json") from error
                    cleaned = normalize(key, rows)
                    page = dict(url=url, next=next_url(key, url, headers), etag=headers.get("etag"),
                                lastModified=headers.get("last-modified"), records=cleaned, bodySha256=hashlib.sha256(body).hexdigest())
                pages.append(page)
                records.extend(page["records"])
                url = page["next"]
            records.sort(key=lambda r:r["remoteId"])
            good = dict(observedAt=stamp(now), records=records, pages=pages, sha256=digest(records))
            validate_good(key, good)
            missing = sorted({r["remoteId"] for r in entry["lastGood"]["records"]} - {r["remoteId"] for r in records})
            added = sorted({r["remoteId"] for r in records} - {r["remoteId"] for r in entry["lastGood"]["records"]})
            if missing:
                # Deletions/private transitions never silently remove a reviewed or cached item.
                entry["pending"] = good
                entry["status"] = "review_required"
            else:
                entry["lastGood"] = good
                entry["pending"] = None
                entry["status"] = "unchanged" if all(s == 304 for s in statuses) else "fresh"
                entry["lastValidatedAt"] = stamp(now)
                if any(s == 200 for s in statuses):
                    entry["lastSuccessfulFetchAt"] = stamp(now)
            entry["failure"], entry["backoffUntil"] = None, None
            report["collections"][key] = dict(action="review" if missing else "validated", status=entry["status"],
                httpStatuses=statuses, observedRecords=len(records), retainedRecords=len(entry["lastGood"]["records"]),
                addedRemoteIds=added, missingRemoteIds=missing, lastGoodSha256=entry["lastGood"]["sha256"])
        except (Invalid, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            code = str(error) if isinstance(error, Invalid) else "network_failure"
            entry["status"] = "stale"
            entry["failure"] = dict(code=code, httpStatus=failure_status)
            report["collections"][key] = dict(action="retained", status="stale", failure=entry["failure"],
                httpStatuses=statuses, retainedRecords=len(entry["lastGood"]["records"]), lastGoodSha256=entry["lastGood"]["sha256"])
    validate_state(result)
    report["allCollectionsValidated"] = all(v["action"] in {"validated", "cached"} and v["status"] in {"fresh", "unchanged"} for v in report["collections"].values())
    return result, report

def atomic_write(path, value):
    fd, name = tempfile.mkstemp(prefix=".sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
