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

print()
if failures:
    print(f"{len(failures)} FAILED")
    for f in failures:
        print("   ", f)
    sys.exit(1)
print("all passed")
