# Fixtures

🚨 **Every byte here is invented.** No real posting, employer, candidate or requisition ID
appears in this directory. The companies are the standard fictional ones.

They are **structurally** accurate, though: each file matches the shape that platform's public
API really returns, because a fixture that does not match reality tests a parser nobody has.

Each one also carries a case that actually broke something:

| file | the case it protects |
|---|---|
| `greenhouse.json` | the description arrives **entity-escaped**, sometimes twice. Strip tags before unescaping and the markup survives as literal words in the archive. |
| `greenhouse-embed.json` | the **embedded board**: the company hosts its own careers page, the board token never appears in the URL, and only `gh_jid` identifies the posting. |
| `ashby.json` | compensation arrives as a **structured** `compensationTierSummary`, so the body scan must not override it. |
| `lever.json` | the body is split across `description`, a `lists` array and `additional`. Reading only `description` silently truncates the posting. |
| `workday.json` | everything is nested under `jobPostingInfo`, and the pay range sits in **markup** with the label in a separate element. |
