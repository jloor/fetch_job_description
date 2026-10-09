#!/usr/bin/env python3
"""
fetch_job_description — keep a job posting exactly as it was when you applied.

Detects the ATS behind a posting URL, calls that platform's public JSON API, and emits a
`job-description.md` block: a metadata table plus the FULL posting text, unedited.

    fetch-job-description <url>                  # print to stdout
    fetch-job-description <url> --new <dir>      # write a fresh job-description.md
    fetch-job-description <url> --append <dir>   # append a verbatim block to an existing one
    fetch-job-description <url> --json           # dump the raw API payload

Supported: Greenhouse (incl. gh_jid embeds), Ashby, Lever, Workday. Anything else falls back
to fetching the page and stripping tags, which is lossier but usually still usable.

Why this exists, and how it differs from the many ATS scrapers:

A scraper NORMALISES. It reads six platforms, flattens them into one schema, and gives you a
searchable index of what is open right now. That is a discovery tool, and there are good ones.

This does the opposite on purpose. It keeps ONE posting, VERBATIM, because a posting is the
record of what you applied to and postings get pulled, rewritten and quietly re-priced. Comp
ranges, remote status and work hours are the fields that move. The metadata header captures
them exactly as stated, so that if a number changes during negotiation there is something to
point at. Nothing is summarised. Typos are not fixed. Normalising would destroy the evidence.

Archiving by hand is where this silently gets skipped, which is the whole problem.

Requires nothing but a Python interpreter. No third-party packages.
"""
import re, sys, json, html, argparse, datetime, urllib.request
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Honest identification. These are public JSON APIs and there is no reason to claim to be a
# browser. Add the repository URL here once the project has one.
UA = "fetch-jd/1.0"

# One source of truth for URL shapes, so detect() and the fetchers cannot disagree.
RE_GREENHOUSE = re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([^/]+)/jobs/(\d+)")
RE_ASHBY = re.compile(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{16,})")
RE_LEVER = re.compile(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{16,})")
RE_WORKDAY = re.compile(r"https://([^.]+)\.([^.]+)\.myworkdayjobs\.com/([^/]+)/job/(.+)$")


def detect(url):
    """Which ATS is behind this URL, from the URL alone. No network, so it is testable.

    A bare gh_jid query parameter counts as Greenhouse: that is the embedded-board case,
    where the company hosts the careers page and only the job id survives in the URL.
    """
    if RE_GREENHOUSE.search(url) or parse_qs(urlparse(url).query).get("gh_jid"):
        return "Greenhouse"
    if RE_ASHBY.search(url):
        return "Ashby"
    if RE_LEVER.search(url):
        return "Lever"
    if RE_WORKDAY.search(url):
        return "Workday"
    return None


def get(url, post=None):
    """Fetch a URL and return the body as text. Returns "" on any failure.

    urllib rather than a curl subprocess, so the only dependency is Python itself.
    Failure returns "" because every caller already reads an unparseable body as "this
    platform did not match", and raising here would abort a run over one dead endpoint.
    """
    data = post.encode("utf-8") if post is not None else None
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, data=data, headers=headers), timeout=40) as r:
            return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception:
        return ""


def detag(h):
    """HTML -> text.

    Order matters. Several ATS APIs return the description ENTITY-ESCAPED (&lt;div&gt;),
    sometimes doubly. Stripping tags before unescaping leaves the markup behind as literal
    words, which poison term extraction (span, div class, data-ccp-parastyle). So unescape
    to a fixed point FIRST, then strip. Found 2026-08-11, in downstream term-extraction
    output that was full of literal markup words.
    """
    h = h or ""
    for _ in range(3):
        u = html.unescape(h)
        if u == h:
            break
        h = u
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<(br|/p|/div|/li|/h[1-6]|/tr|/table)\s*/?>", "\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h).replace("\xa0", " ").replace("\u2019", "'")
    h = re.sub(r"[ \t]+", " ", h)
    h = re.sub(r"\n\s*\n\s*\n+", "\n\n", h)
    h = "\n".join(l.rstrip() for l in h.split("\n")).strip()
    return re.sub(r"^(-\s*\n)+", "", h, flags=re.M)


# ---------------------------------------------------------------- platforms
def greenhouse(url):
    q = parse_qs(urlparse(url).query)
    jid = (q.get("gh_jid") or [None])[0]
    m = RE_GREENHOUSE.search(url)
    token, job = (m.group(1), m.group(2)) if m else (None, jid)
    if not token and job:               # embedded board (datadog, pinterest, alloy…)
        labels = [l for l in urlparse(url).netloc.split(".") if l not in ("www", "com", "io", "co")]
        cands = []
        for l in labels:
            base = re.sub(r"(careers?|jobs?|apply)", "", l).strip("-") or l
            cands += [base, re.sub(r"(hq|inc|labs|technologies|software)$", "", base)]
        seen, uniq = set(), []
        for cnd in cands:
            if cnd and len(cnd) > 1 and cnd not in seen:
                seen.add(cnd); uniq.append(cnd)
        for g in uniq:
            d = get(f"https://boards-api.greenhouse.io/v1/boards/{g}/jobs/{job}?content=true")
            if d.strip().startswith("{") and '"title"' in d:
                token = g
                break
    if not token or not job:
        return None
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job}?content=true")
    try:
        j = json.loads(d)
    except Exception:
        return None
    if "title" not in j:
        return None
    return {"ats": "Greenhouse", "title": j["title"], "raw": j,
            "location": (j.get("location") or {}).get("name", ""),
            "updated": (j.get("updated_at") or "")[:10],
            "url": j.get("absolute_url", url), "body": detag(j.get("content", ""))}


def ashby(url):
    m = RE_ASHBY.search(url)
    if not m:
        return None
    token, jid = m.groups()
    try:
        board = json.loads(get(
            f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"))
    except Exception:
        return None
    j = next((x for x in board.get("jobs", []) if jid in x.get("jobUrl", "")), None)
    if not j:
        return None
    comp = (j.get("compensation") or {}).get("compensationTierSummary", "")
    return {"ats": "Ashby", "title": j["title"], "raw": j,
            "location": j.get("location", ""), "comp": comp,
            "updated": (j.get("publishedAt") or "")[:10],
            "remote": j.get("isRemote"), "url": j.get("jobUrl", url),
            "apply": j.get("applyUrl", ""), "body": detag(j.get("descriptionHtml", ""))}


def lever(url):
    m = RE_LEVER.search(url)
    if not m:
        return None
    token, jid = m.groups()
    try:
        j = json.loads(get(f"https://api.lever.co/v0/postings/{token}/{jid}?mode=json"))
    except Exception:
        return None
    if "text" not in j:
        return None
    body = detag(j.get("description", ""))
    for lst in j.get("lists", []):
        body += "\n\n" + (lst.get("text") or "") + "\n" + detag(lst.get("content", ""))
    if j.get("additional"):
        body += "\n\n" + detag(j["additional"])
    cat = j.get("categories") or {}
    return {"ats": "Lever", "title": j["text"], "raw": j,
            "location": cat.get("location", ""), "team": cat.get("team", ""),
            "url": j.get("hostedUrl", url), "apply": j.get("applyUrl", ""), "body": body}


def workday(url):
    m = RE_WORKDAY.search(url)
    if not m:
        return None
    tenant, sub, site, path = m.groups()
    api = f"https://{tenant}.{sub}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{path}"
    try:
        j = json.loads(get(api))["jobPostingInfo"]
    except Exception:
        return None
    return {"ats": "Workday", "title": j.get("title", ""), "raw": j,
            "location": j.get("location", ""), "updated": (j.get("startDate") or "")[:10],
            "req": j.get("jobReqId", ""), "url": j.get("externalUrl", url),
            "body": detag(j.get("jobDescription", ""))}


def looks_like_single_posting(url):
    """Does this URL point at one requisition, rather than a board of many? No network.

    A board page still returns plenty of text, so length alone cannot tell them apart.
    The signal is in the path: a long numeric id, a UUID prefix, or a /job/<x>/<y> shape.
    """
    path = urlparse(url).path.rstrip("/")
    return bool(re.search(r"/\d{4,}|[0-9a-f]{8}-[0-9a-f]{4}|/job[s]?/[^/]+/[^/]+", path)
                or parse_qs(urlparse(url).query))


def generic(url):
    """Fallback scrape. Refuses board and listing pages: a directory of open roles is not a
    posting, and archiving one produces a file that looks right and is worthless."""
    if not looks_like_single_posting(url):
        sys.exit(
            f"\n  ERROR: {url}\n  looks like a job BOARD or listing page, not a single posting.\n"
            "  Archiving a directory of open roles would give you a file that looks like an\n"
            "  archive and contains no posting.\n\n"
            "  Pass the URL of the specific requisition. If the req is already gone, record\n"
            "  that as a loss rather than archiving the board in its place.\n")
    body = detag(get(url))
    if len(body) < 400:
        return None
    return {"ats": "generic HTML scrape", "title": "", "location": "", "url": url,
            "body": body, "raw": {}}


def fetch(url):
    for fn in (greenhouse, ashby, lever, workday):
        r = fn(url)
        if r and r.get("body", "").strip():
            return r
    return generic(url)



# ---------------------------------------------------------------- comp in the body
#
# ⭐ WHY THIS EXISTS. A posting is evidence, and the field most likely to move between the
# posting and the offer is pay. Several ATSes have a structured compensation field and most
# postings leave it empty, while stating the range in the text a paragraph later. Dropping
# the row in that case makes "the employer published nothing" and "we did not look" identical
# in the archive, which is the one distinction an evidence tool must never blur.
#
# 🚨 A BARE MONEY REGEX REPORTS THE WRONG NUMBER, CONFIDENTLY. The GoFundMe posting used in
# the README says "raised more than $40 billion since 2010". Scanning for currency alone
# archives that as the salary. So a match must satisfy ALL of:
#   1. two amounts, read as a range
#   2. pay vocabulary in the same sentence, not merely somewhere in the document
#   3. magnitudes that could actually be pay
# and the sentence it came from is archived beside it, so the reader checks rather than trusts.

# ⚠️ Must not end on a comma. "$125,000, as well as stock options" otherwise
# captures "$125,000," and the trailing punctuation lands in the archive.
_AMOUNT = r"\$\s?\d(?:[\d,]*\d)?(?:\.\d+)?\s*[KkMm]?"
# 🚨 A unit after the FIRST figure hid the range, and the single-figure pass then archived a
# wrong band: "$140,000/yr - $150,000/yr" became "$140,000 - $140,000" (Global-e, 2026-10-09).
# The unit is allowed between the figures and never captured. The engine carries the same line.
_UNIT = r"(?:\s?/\s?(?:yr|year|hr|hour|annum))?"
_RANGE = re.compile(rf"({_AMOUNT}){_UNIT}\s*(?:-|–|—|to|and)\s*({_AMOUNT})")

# 🚨 A BAND WITHOUT A DOLLAR SIGN IS STILL A BAND. Businessolver, read on 2026-09-19:
# "The pay range for this position is 67K to 105K per year". The posting was carried as
# NONE STATED, which is a different and much more interesting claim than 67K.
# ⚠️ Narrow on purpose: a bare integer in a posting is usually not money ("7+ years",
# "2,000 clients", "1998"), so only a K suffix or explicit comma-thousands counts, and only
# inside a sentence that already mentions pay. Both guards are needed: one real posting
# says "$100 billion in charitable giving" and "a $140 million growth investment" in prose.
_BARE = r"\d{2,3}\s?[Kk]\b|\d{2,3},\d{3}\b"
_BARE_RANGE = re.compile(rf"({_BARE}){_UNIT}\s*(?:-|–|—|to|and)\s*({_BARE})")
_SINGLE = re.compile(
    rf"({_AMOUNT}|{_BARE})\s*(?:per year|per annum|annually|annualized|/\s?yr|a year)"
    rf"|(?:salary|base pay|pay|compensation)\s*(?:is|of|:)\s*({_AMOUNT}|{_BARE})", re.I)
_PAY_WORDS = re.compile(
    r"salary|compensation|pay range|pay band|base pay|base range|hourly|per hour|"
    r"per year|per annum|annually|annualized|OTE|on[- ]target earnings|"
    r"total target cash|expected pay|range for this (?:role|position)", re.I)


def _to_number(tok):
    """'$95,000' -> 95000 ; '$95K' -> 95000 ; '$1.2M' -> 1200000"""
    t = tok.replace("$", "").replace(",", "").strip()
    mult = 1
    if t and t[-1] in "Kk":
        mult, t = 1_000, t[:-1]
    elif t and t[-1] in "Mm":
        mult, t = 1_000_000, t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


def body_comp(body):
    """Return (range_text, evidence_sentence) found in the posting text, or (None, None).

    ⚠️ Deliberately conservative. A missed range leaves the row as NONE STATED, which is
    honest. A wrong range is worse than no range, because it looks like a record.
    """
    # ⚠️ DETAG FIRST. A live fetch arrives already stripped, but an archived posting can
    # still hold raw markup, and Greenhouse renders a pay range as
    # "<span>$210,000</span><span class="divider">&mdash;</span><span>$250,000</span>".
    # The two numbers are 49 characters apart and the thing between them is not a dash, so
    # a range pattern reading the markup finds nothing. detag() is idempotent on text that
    # is already clean, so this costs nothing in the normal case.
    body = detag(body) if body and "<" in body else (body or "")

    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        if not _PAY_WORDS.search(sentence):
            continue
        # ⚠️ ORDER MATTERS. The priced pattern runs first, so "$67,000 to $105,000" can
        # never be read as a bare "67 to 105" by the looser one.
        m = _RANGE.search(sentence) or _BARE_RANGE.search(sentence)
        if not m:
            continue
        lo, hi = _to_number(m.group(1)), _to_number(m.group(2))
        if lo is None or hi is None or lo > hi:
            continue
        hourly = bool(re.search(r"hourly|per hour|/\s?hr|an hour", sentence, re.I))
        # Plausibility. Without this "$40 billion" and "$5 - $10 off" both qualify.
        ok = (10 <= lo <= 500 and 10 <= hi <= 500) if hourly else \
             (15_000 <= lo <= 2_000_000 and 15_000 <= hi <= 2_000_000)
        if not ok:
            continue
        # 📌 The AMOUNTS are verbatim; only the separator is normalised, because an em
        # dash, an en dash and the word "to" all mean the same thing and a reader
        # comparing two archives should not have to notice which was used. The
        # unaltered sentence is returned alongside, so nothing is taken on trust.
        return f"{m.group(1).strip()} - {m.group(2).strip()}", " ".join(sentence.split())[:300]

    # ⚠️ SECOND PASS, FOR STRUCTURE RATHER THAN PROSE. Greenhouse renders pay transparency as
    # markup: "The annual compensation range for this role is listed below" sits in one
    # element and the numbers in another, so they are never in the same sentence. Requiring
    # one sentence missed $210,000 - $250,000 in a real archived posting.
    #
    # 🚨 The window is small on purpose. Widening it far enough to be generous reintroduces
    # exactly the failure the sentence rule prevents: a document mentioning salary anywhere
    # and "$40 billion" anywhere becomes a match. 240 characters spans a label and its
    # adjacent value without spanning unrelated paragraphs.
    flat = " ".join(body.split())
    for m in _RANGE.finditer(flat):
        before = flat[max(0, m.start() - 240):m.start()]
        if not _PAY_WORDS.search(before):
            continue
        lo, hi = _to_number(m.group(1)), _to_number(m.group(2))
        if lo is None or hi is None or lo > hi:
            continue
        hourly = bool(re.search(r"hourly|per hour|/\s?hr|an hour", before, re.I))
        ok = (10 <= lo <= 500 and 10 <= hi <= 500) if hourly else \
             (15_000 <= lo <= 2_000_000 and 15_000 <= hi <= 2_000_000)
        if not ok:
            continue
        ctx = flat[max(0, m.start() - 160):m.end() + 40]
        return f"{m.group(1).strip()} - {m.group(2).strip()}", ctx.strip()[:300]

    # ⭐ THIRD PASS: ONE NUMBER, NOT TWO. Feathr states "$55,000 annually, and up to a 10%
    # bonus potential": a single figure, no range, and the posting was carried as NONE
    # STATED. It is last so that any real range wins first, and it only reads a number that
    # sits directly beside the words for a period, so a sentence mentioning compensation
    # and some unrelated figure cannot become a band.
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        if not _PAY_WORDS.search(sentence):
            continue
        m = _SINGLE.search(sentence)
        if not m:
            continue
        tok = m.group(1) or m.group(2)
        val = _to_number(tok)
        if val is None:
            continue
        hourly = bool(re.search(r"hourly|per hour|/\s?hr|an hour", sentence, re.I))
        ok = (10 <= val <= 500) if hourly else (15_000 <= val <= 2_000_000)
        if not ok:
            continue
        # 📌 Written as a range whose ends are equal, because that is what the employer
        # said: one number, not a band collapsed from two.
        return f"{tok.strip()} - {tok.strip()}", " ".join(sentence.split())[:300]
    return None, None

# ---------------------------------------------------------------- output

def _comp_row(d):
    """The compensation cell, with its PROVENANCE, and never silently absent.

    Three distinguishable states, which is the whole point:
      the platform published a field        -> the value
      only the text states a range          -> the value, marked as body-sourced
      neither                               -> NONE STATED
    """
    structured = (d.get("comp") or "").strip()
    if structured:
        return structured
    found, evidence = body_comp(d.get("body", ""))
    if found:
        return f"{found} (from the posting text, not a structured field: \"{evidence}\")"
    return "NONE STATED"


def block(d, url):
    today = datetime.date.today().isoformat()
    rows = [("ATS", d["ats"]), ("Title", d.get("title", "")),
            ("Canonical URL", d.get("url", url)), ("Apply URL", d.get("apply", "")),
            ("Location as stated", d.get("location", "")), ("Team", d.get("team", "")),
            ("Req ID", d.get("req", "")), ("Comp as stated", _comp_row(d)),
            ("isRemote flag", "" if d.get("remote") is None else str(d.get("remote"))),
            ("Posted / updated", d.get("updated", "")), ("Captured", today)]
    # ⚠️ "Comp as stated" is ALWAYS emitted, even when empty. Every other row is dropped
    # when blank, which is right for a missing team name and wrong for pay: an omitted row
    # cannot be told apart from a field nobody looked for, and pay is the one field this
    # archive exists to be able to point at later.
    tbl = "\n".join(f"| **{k}** | {v} |" for k, v in rows
                    if str(v).strip() or k == "Comp as stated")
    return (f"\n---\n\n## Full posting text (verbatim, captured {today})\n\n"
            f"| Field | Value |\n|---|---|\n{tbl}\n\n"
            f"_Fetched with `fetch-job-description`. Do not edit below this line: it is the "
            f"record "
            f"of what was actually posted._\n\n{d['body']}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--append", type=Path, help="package dir: append verbatim block to job-description.md")
    ap.add_argument("--new", type=Path, help="package dir: write a fresh job-description.md")
    ap.add_argument("--json", action="store_true", help="dump the raw API payload")
    a = ap.parse_args()

    d = fetch(a.url)
    if not d:
        sys.exit("could not fetch a posting body from that URL")
    if a.json:
        print(json.dumps(d.get("raw", {}), indent=1)[:20000])
        return

    out = block(d, a.url)
    tgt = a.append or a.new
    if not tgt:
        print(out)
        return

    tgt.mkdir(parents=True, exist_ok=True)
    f = tgt / "job-description.md"
    if a.new or not f.exists():
        head = f"# {d.get('title') or 'Job'}\n"
        f.write_text(head + out, encoding="utf-8")
        print(f"wrote {f}  ({len(d['body'])} chars of posting text)")
    else:
        cur = f.read_text(encoding="utf-8")
        if "Full posting text" in cur:
            sys.exit(f"{f} already has a verbatim block. Delete it first, or use --new.")
        f.write_text(cur.rstrip() + "\n" + out, encoding="utf-8")
        print(f"appended to {f}  ({len(d['body'])} chars of posting text)")


if __name__ == "__main__":
    main()
