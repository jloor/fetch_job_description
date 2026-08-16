# fetch_job_description

**Keep a job posting exactly as it was when you applied.**

Postings get pulled, rewritten, and quietly re-priced. Compensation ranges, remote status and
work hours are the fields that move. If a number changes between the posting you read and the
offer you are discussing, you want something to point at.

```
fetch-job-description https://job-boards.greenhouse.io/gofundme/jobs/8089835 --new ./gofundme-tse
```

Writes `job-description.md`. Real output, unedited:

```markdown
---

## Full posting text (verbatim, captured 2026-08-16)

| Field | Value |
|---|---|
| **ATS** | Greenhouse |
| **Title** | Technical Support Engineer I |
| **Canonical URL** | https://job-boards.greenhouse.io/gofundme/jobs/8089835 |
| **Location as stated** | Remote |
| **Posted / updated** | 2026-08-06 |
| **Captured** | 2026-08-16 |

_Fetched with `fetch-job-description`. Do not edit below this line: it is the record of what was actually posted._

Want to help us help others? We're hiring!

 GoFundMe is the world's most powerful community for good, dedicated to helping people
 help each other...
```

Greenhouse publishes no structured compensation for this posting, no requisition ID and no
apply URL, so those rows are absent. **Compensation is the exception: it is always emitted.**
Here the range was found in the posting text and is marked as such:

```
| **Comp as stated** | $59,500 - $82,000 (from the posting text, not a structured field:
                       "salary range for this full-time position is $59,500 - $82,000.") |
```

Three states, kept distinguishable on purpose:

| | |
|---|---|
| the platform published a field | the value, as given |
| only the text states a range | the value, marked body-sourced, with the sentence quoted |
| neither | `NONE STATED` |

An omitted pay row cannot be told apart from a pay row nobody looked for, and pay is the field
this archive most exists to be able to point at later.

⚠️ Finding a range in prose is where a naive tool gets confidently wrong. The posting above
also contains "raised more than **$40 billion** since 2010". A match must be a range, sit in a
sentence using pay vocabulary, and be a plausible magnitude, and the sentence it came from is
archived beside it so you can check rather than trust.

## This is not a job scraper

There are good ATS scrapers. They read Greenhouse, Lever, Ashby, Workday and others, flatten
six schemas into one, and give you a searchable index of everything open right now. If you want
to *find* jobs, use one of those.

This tool does the opposite thing on purpose.

| a scraper | this |
|---|---|
| normalises into one schema | refuses to normalise |
| many postings, latest state | one posting, as it was |
| for discovery | for evidence |
| summarises and cleans | keeps typos, keeps formatting, changes nothing |

Normalising is exactly what destroys the value here. A tidied posting is no longer the record
of what you agreed to apply for.

## What it supports

Greenhouse (including `gh_jid` embeds on a company's own careers page), Ashby, Lever, and
Workday, each through that platform's own public JSON API. Anything unrecognised falls back to
fetching the page and stripping tags, which is lossier but usually still usable.

It refuses to archive a **board page**. A list of open roles returns plenty of text and looks
like a successful capture, which is worse than an obvious failure.

## Install

Requires Python 3.11 or newer. No third-party packages, no API keys, no login.

```
git clone https://github.com/<owner>/fetch_job_description
cd fetch_job_description
python3 fetch_job_description/archive.py <url>
```

## Usage

```
fetch-job-description <url>                  print to stdout
fetch-job-description <url> --new <dir>      write a fresh job-description.md
fetch-job-description <url> --append <dir>   append a verbatim block to an existing one
fetch-job-description <url> --json           dump the raw API payload
```

`--append` exists because a posting you are tracking can be re-captured later. Two verbatim
blocks with two capture dates is how you show that the range moved.

## Tests

```
python3 tests/test_archive.py
```

No network. Everything under test is a pure function, and the assertions are shaped around what
has actually gone wrong:

- **ATS detection**, including the embedded-board case where the board token is absent from the
  URL and only `gh_jid` survives.
- **Board-page refusal**, because length cannot distinguish a list of roles from a posting.
- **Unescape before strip.** Several ATS APIs return the description entity-escaped, some of
  them twice. Strip first and the markup survives as literal words in the archive.

## Support

None promised. This is code that runs a real job search, published because the problem is
common. Issues are read. Pull requests are not accepted.

## Licence

MIT.
