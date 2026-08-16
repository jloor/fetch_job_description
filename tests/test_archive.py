#!/usr/bin/env python3
"""
Tests for fetch_job_description. No network: everything here is a pure function.

The three things worth protecting are the three that have actually gone wrong or that
carry the knowledge:

  detect()                  which ATS is behind a URL, including the embedded-board case
                            where the board token is absent and only gh_jid survives
  looks_like_single_posting()  a board page returns plenty of text, so length cannot tell
                            it apart from a posting. Getting this wrong archives a
                            directory of open roles in a file that looks correct.
  detag()                   several ATS APIs return the description entity-escaped, some
                            of them twice. Strip before unescape and the markup survives
                            as literal words. Found 2026-08-11.

Run:  python3 tests/test_archive.py
"""
import importlib.util, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("archive", HERE.parent / "fetch_job_description" / "archive.py")
fj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fj)

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:<52} {got!r}")
    if not ok:
        failures.append(f"{label}: got {got!r}, want {want!r}")


print("ATS detection from the URL alone:")
for url, want in [
    ("https://job-boards.greenhouse.io/tailscale/jobs/4709946005", "Greenhouse"),
    ("https://boards.greenhouse.io/array/jobs/6109957004", "Greenhouse"),
    ("https://boards.eu.greenhouse.io/nice/jobs/4871267101", "Greenhouse"),
    ("https://job-boards.eu.greenhouse.io/aidocmedical/jobs/4905355101", "Greenhouse"),
    # The embedded-board case: the company hosts the page, the board token is nowhere in
    # the URL, and only gh_jid identifies the job. This is the one worth publishing.
    ("https://www.datadoghq.com/careers/detail/?gh_jid=7961297", "Greenhouse"),
    ("https://jobs.ashbyhq.com/ashby/8341d4ba-5f07-4b40-a398-14a83092ab5f", "Ashby"),
    ("https://jobs.lever.co/tonkean/2ce218e7-5c24-4933-867e-65e1502563db", "Lever"),
    ("https://ddcdine.wd501.myworkdayjobs.com/DDC_Careers/job/Remote/Support_JR100276",
     "Workday"),
    ("https://example.com/careers/engineering", None),
]:
    check(url.split("//")[1][:48], fj.detect(url), want)

print("\nposting vs board page:")
for url, want in [
    ("https://jobs.ashbyhq.com/ashby/8341d4ba-5f07-4b40-a398-14a83092ab5f", True),
    ("https://job-boards.greenhouse.io/tailscale/jobs/4709946005", True),
    ("https://ddcdine.wd501.myworkdayjobs.com/DDC_Careers/job/Remote/Support_JR100276", True),
    ("https://www.datadoghq.com/careers/detail/?gh_jid=7961297", True),
    # Boards. Each of these returns a page full of text that is not a posting.
    ("https://jobs.ashbyhq.com/hellopatient", False),
    ("https://jobs.ashbyhq.com/ashby", False),
    ("https://example.com/careers", False),
    ("https://example.com/jobs/", False),
]:
    check(url.split("//")[1][:48], fj.looks_like_single_posting(url), want)

print("\ndetag, the unescape-before-strip order (the 2026-08-11 bug):")
# Singly escaped: one unescape pass exposes the tags, then they are stripped.
once = "&lt;div class=&quot;x&quot;&gt;Hello&lt;/div&gt;"
# Doubly escaped, which is what actually shipped from at least one ATS.
twice = "&amp;lt;div class=&amp;quot;x&amp;quot;&amp;gt;Hello&amp;lt;/div&amp;gt;"
for label, raw in [("singly escaped", once), ("doubly escaped", twice)]:
    out = fj.detag(raw)
    check(f"{label}: text survives", "Hello" in out, True)
    check(f"{label}: no literal 'div'", "div" in out, False)
    check(f"{label}: no literal 'class'", "class" in out, False)

print("\ndetag, ordinary markup:")
# Blank-line separated, because </li> emits a newline and the next <li> emits another.
# It still renders as a list in markdown, and tightening it would change the bytes of
# every archive this tool has already written. Asserted as-is deliberately.
check("list items become dashes", fj.detag("<ul><li>one</li><li>two</li></ul>"), "- one\n\n- two")
check("script contents dropped", "alert" in fj.detag("<script>alert(1)</script>hi"), False)
check("empty input", fj.detag(""), "")
check("none input", fj.detag(None), "")
check("nbsp becomes a space", fj.detag("a&nbsp;b"), "a b")
check("curly apostrophe normalised", fj.detag("don’t"), "don't")

# ── compensation in the body ──────────────────────────────────────────────────
# ⚠️ EVERY CASE HERE IS A TRAP THAT A BARE MONEY REGEX FALLS INTO. The first one is real:
# the GoFundMe posting used in the README says "raised more than $40 billion since 2010",
# and a scan for currency alone archives that as the salary.
print("\ncompensation found in the posting text:")
for _text, _want in [
    ("raised more than $40 billion since 2010.", None),
    ("Our customers have processed $2M - $5M in volume.", None),
    ("Save $5 - $10 off your first order.", None),
    ("We offer a salary and also raised $40 - $80 million in Series C.", None),
    ("The annual U.S. salary range for this full-time position is $59,500 - $82,000.",
     "$59,500 - $82,000"),
    # A trailing comma belongs to the sentence, not to the number.
    ("Compensation for this role ranges from $105,000 - $125,000, as well as stock options.",
     "$105,000 - $125,000"),
    # Em dash, en dash and "to" all mean the same thing; the separator is normalised while
    # the amounts stay exactly as written.
    ("Annual Salary: $210,000 \u2014 $250,000 USD", "$210,000 - $250,000"),
    ("Base pay range: $95K \u2013 $120K annually.", "$95K - $120K"),
    ("The hourly rate for this role is $25 - $30 per hour.", "$25 - $30"),
]:
    _got, _ev = fj.body_comp(_text)
    check(f"body comp: {_text[:44]}", _got, _want)

# The three states must stay distinguishable. An omitted pay row and a pay row nobody
# looked for are the same thing to a reader, and that is the failure this prevents.
check("a structured field wins over the body",
      fj._comp_row({"comp": "$100K - $150K", "body": "salary range $1 - $2 per hour"}),
      "$100K - $150K")
check("nothing anywhere is stated explicitly",
      fj._comp_row({"body": "We are hiring a support engineer."}), "NONE STATED")
check("a body-sourced range says so, and quotes the sentence",
      "from the posting text" in fj._comp_row(
          {"body": "The salary range for this role is $59,500 - $82,000."}), True)
# 🚨 THE CASE THAT MOTIVATED detag() INSIDE body_comp. Greenhouse renders a pay range as
# markup, so the two numbers sit 49 characters apart with tags and an &mdash; entity between
# them, not a separator. A range pattern reading the raw HTML finds nothing, and this is the
# single highest-value number in a real archive.
check("a pay range buried in markup is still found",
      fj.body_comp('<div class="pay-input"><div>Annual Salary:</div>'
                   '<div class="pay-range"><span>$210,000</span>'
                   '<span class="divider">&mdash;</span><span>$250,000</span></div></div>')[0],
      "$210,000 - $250,000")
check("the comp row survives the empty-row filter",
      "Comp as stated" in fj.block({"ats": "x", "body": "nothing here"}, "http://x"), True)

# ── the four platform parsers, against synthetic payloads ─────────────────────
# ⭐ WHY THESE EXIST. Everything above tests a pure function. These exercise the FETCH path
# end to end with the network stubbed, which is the half a reader cannot otherwise see:
# what each API actually returns and what the tool makes of it. The fixtures are invented
# but structurally accurate, because a fixture that does not match reality tests a parser
# nobody has.
import json as _json, pathlib as _pl
_FIX = _pl.Path(__file__).resolve().parent / "fixtures"


def _stub(payload):
    """Replace the module's HTTP with a fixed body. Nothing here touches the network."""
    fj.get = lambda url, post=None: payload


print("\nplatform parsers, network stubbed:")

# GREENHOUSE — the description arrives entity-escaped. Strip before unescape and the markup
# survives as literal words, which is the bug that motivated detag's ordering.
_stub((_FIX / "greenhouse.json").read_text())
_g = fj.greenhouse("https://job-boards.greenhouse.io/northwind/jobs/1234567")
check("greenhouse: parsed", _g["ats"], "Greenhouse")
check("greenhouse: title", _g["title"], "Support Engineer")
check("greenhouse: location", _g["location"], "Remote - US")
check("greenhouse: escaped HTML became readable text",
      "Own tier-2 cases end to end" in _g["body"], True)
check("greenhouse: and no markup survived as words",
      "&lt;" in _g["body"] or "<p>" in _g["body"], False)
check("greenhouse: pay recovered from the prose",
      fj.body_comp(_g["body"])[0], "$95,000 - $120,000")

# The EMBEDDED BOARD: no token in the URL, only gh_jid identifies the posting.
check("embedded board is detected as Greenhouse",
      fj.detect("https://careers.contoso.example/jobs?gh_jid=7654321"), "Greenhouse")
_stub((_FIX / "greenhouse-embed.json").read_text())
_e = fj.greenhouse("https://careers.contoso.example/jobs?gh_jid=7654321")
check("embedded board: parsed without a board token", _e["title"],
      "Implementation Consultant")

# ASHBY returns the whole board; the posting is matched by the UUID inside jobUrl.
_stub((_FIX / "ashby.json").read_text())
_a = fj.ashby("https://jobs.ashbyhq.com/globex/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
check("ashby: the RIGHT posting is picked from the board", _a["title"],
      "Product Support Engineer")
check("ashby: structured compensation is read", _a["comp"],
      "$110,000 - $140,000 • Offers Equity")
check("ashby: isRemote survives", _a["remote"], True)
# ⚠️ A structured field must WIN over anything the body scan finds.
check("ashby: the structured field beats the body scan",
      fj._comp_row(_a), "$110,000 - $140,000 • Offers Equity")

# LEVER splits the posting across three fields. Reading only `description` truncates it.
_stub((_FIX / "lever.json").read_text())
_l = fj.lever("https://jobs.lever.co/initech/11111111-2222-3333-4444-555555555555")
check("lever: parsed", _l["title"], "Technical Account Manager")
check("lever: the lists array is appended, not dropped",
      "Own a portfolio of named accounts" in _l["body"], True)
check("lever: the additional block is appended too",
      "$130,000" in _l["body"], True)
check("lever: pay found in the appended block",
      fj.body_comp(_l["body"])[0], "$130,000 - $160,000")

# WORKDAY nests under jobPostingInfo and renders pay as markup with the label elsewhere.
_stub((_FIX / "workday.json").read_text())
_w = fj.workday("https://umbrella.wd1.myworkdayjobs.com/careers/job/New-York/Deployment-Engineer_REQ-00042")
check("workday: unwrapped from jobPostingInfo", _w["title"], "Deployment Engineer")
check("workday: req id read", _w["req"], "REQ-00042")
check("workday: pay range buried in markup is still found",
      fj.body_comp(_w["body"])[0], "$120,000 - $150,000")

print()
if failures:
    print(f"{len(failures)} FAILED")
    for f in failures:
        print("   ", f)
    sys.exit(1)
print("all passed")
