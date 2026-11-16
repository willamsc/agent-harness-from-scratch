# Cardinal Agent v0.1.1 — local preview

An installable employee-assistant CLI with isolated profiles, Markdown/email
imports, source-aware retrieval, persistent memory, saved conversations and
explicitly approved terminal execution. Fictional demo data is included.

Download `code.zip` for source, or install the Python wheel. Check `SHA256SUMS`
and `release-manifest.json` to tie the artifacts to a Git commit. See README
for initialization and API configuration. Python 3.11+ and network access to
a configured model provider are required for live chat; the offline demo
does not need an API key.

This is a single-user preview, not a deployed corporate service. It does not
connect to real company mail/calendar accounts, provide SSO/RBAC, or guarantee
answers and sandbox isolation. Terminal tools are disabled by default; model
prompts and selected evidence are sent to the configured external provider.

The public simulated-user baseline is 18/20 using deepseek-flash across all
roles. Subsequent runs also scored 18/20 with different individual failures;
all results are retained. This is not a production SLA or a claim of company
deployment. Third-party licensing and attribution are preserved in NOTICE.md and LICENSE.
