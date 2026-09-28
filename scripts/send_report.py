#!/usr/bin/env python3
"""Render a Codex bug report / feedback as a self-contained HTML file and send it to a webhook.

Usage:
    send_report.py --data PATH [--dry-run] [--out DIR]

    --data PATH   report-data.json (schema below). Required.
    --dry-run     Render the HTML and print its filename and payload size. No POST; files are kept.
    --out DIR     Directory for the generated HTML (default: the directory of --data).

Env:
    CODEX_REPORT_WEBHOOK_URL   Webhook (Power Automate / Teams) URL. Overrides config/report.json (webhookUrl).

report-data.json schema:
    {
      "reportType": "bug" | "feedback",                          # required
      "brand": str, "project": str,                              # required
      "slug": str,          # short kebab-case ascii             # required
      "title": str,                                              # required
      "summary": str,       # 1-2 sentences                      # required
      "reporter": {"name": str, "email": str},                   # required
      "environment": {"os", "claudeCodeVersion", "model", "pluginVersion",
                      "harnessVersion", "timestamp", "timezone"}, # object required, values may be null
      "context": {"framework", "piece", "intent", "creating"},   # object required, values may be null
      "relatedFiles": [str],                                     # repo-relative paths, may be empty
      "sections": [{"heading": str, "body": str}],               # optional extra notes

      # bug only (all required unless noted)
      "steps": [str],       # >= 1 non-empty step
      "friction": str,      # exact step where it failed + what was tried
      "expected": str, "actual": str,
      "severity": "blocking" | "annoying",
      "reproducible": str | null,                                # optional

      # feedback only (all required)
      "doing": str,         # what they were doing
      "painPoint": str,     # what felt slow / confusing / repetitive
      "proposal": str,      # how they would like it to work
      "gain": str,          # what they would gain
      "area": "framework" | "render" | "copy" | "flow" | "commands" | "other"
    }

Output (stdout, last lines):
    REPORT_SENT=<filename>                 on success (exit 0; generated files are deleted)
    REPORT_PENDING=<absolute path>         on send failure (exit 2; HTML moved to the pending folder)
    Validation errors exit 1.

Pending reports live in ~/.codex-ocx/reports-pending/ and are retried on every run.
The webhook URL is never printed.
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

# The Power Automate webhook (posts reports to the Codex Teams channel) is read from
# config/report.json ({"webhookUrl": "..."}), which ships with the plugin. The
# CODEX_REPORT_WEBHOOK_URL env var overrides it. Never print this value.
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "report.json"

PENDING_DIR = Path.home() / ".codex-ocx" / "reports-pending"
TIMEOUT_SECONDS = 30
REPORT_TYPES = ("bug", "feedback")
TITLES = {"bug": "Codex bug report", "feedback": "Codex feedback"}
SEVERITIES = ("blocking", "annoying")
AREAS = ("framework", "render", "copy", "flow", "commands", "other")


class SendError(Exception):
    """A failed delivery, with a short human-readable reason (never contains the URL)."""


# --- Validation ----------------------------------------------------------------

def validate(data):
    errors = []
    if not isinstance(data, dict):
        return ["top-level JSON must be an object"]
    if data.get("reportType") not in REPORT_TYPES:
        errors.append("reportType must be 'bug' or 'feedback'")
    for key in ("brand", "project", "slug", "title", "summary"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key} is required (non-empty string)")
    reporter = data.get("reporter")
    if not isinstance(reporter, dict):
        errors.append("reporter is required (object with name, email)")
    else:
        for key in ("name", "email"):
            if not isinstance(reporter.get(key), str) or not reporter[key].strip():
                errors.append(f"reporter.{key} is required (non-empty string)")
    for key in ("environment", "context"):
        if not isinstance(data.get(key), dict):
            errors.append(f"{key} is required (object)")
    sections = data.get("sections")
    if sections is not None:
        if not isinstance(sections, list):
            errors.append("sections must be a list of {heading, body} (or omitted)")
        else:
            for i, sec in enumerate(sections):
                if not isinstance(sec, dict) or not isinstance(sec.get("heading"), str) \
                        or not isinstance(sec.get("body"), str):
                    errors.append(f"sections[{i}] must have string 'heading' and 'body'")
    related = data.get("relatedFiles", [])
    if related is not None and (not isinstance(related, list)
                                or not all(isinstance(p, str) for p in related)):
        errors.append("relatedFiles must be a list of strings")

    rtype = data.get("reportType")
    if rtype == "bug":
        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append("steps is required for bug reports (list of at least 1 non-empty string)")
        else:
            for i, step in enumerate(steps):
                if not _nonempty(step):
                    errors.append(f"steps[{i}] must be a non-empty string")
        for key, hint in (("friction", "exact step where it failed and what was tried"),
                          ("expected", "what the user expected to happen"),
                          ("actual", "what actually happened")):
            if not _nonempty(data.get(key)):
                errors.append(f"{key} is required for bug reports (non-empty string: {hint})")
        if data.get("severity") not in SEVERITIES:
            errors.append("severity is required for bug reports: one of " + ", ".join(SEVERITIES))
        repro = data.get("reproducible")
        if repro is not None and not isinstance(repro, str):
            errors.append("reproducible must be a string or null")
    elif rtype == "feedback":
        for key, hint in (("doing", "what they were doing in Codex"),
                          ("painPoint", "what felt slow, confusing or repetitive"),
                          ("proposal", "how they would like it to work"),
                          ("gain", "what they would gain")):
            if not _nonempty(data.get(key)):
                errors.append(f"{key} is required for feedback (non-empty string: {hint})")
        if data.get("area") not in AREAS:
            errors.append("area is required for feedback: one of " + ", ".join(AREAS))
    return errors


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


# --- Helpers -------------------------------------------------------------------

def slugify(value, max_len=40):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:max_len].strip("-") or "report"


def summary_text(data):
    text = (data.get("summary") or "").strip() or (data.get("title") or "")
    text = text.replace('"', "").replace("\\", "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 200:
        text = text[:199].rstrip() + "…"
    return text


def esc(value):
    if value is None or value == "":
        return '<span class="muted">—</span>'
    return html.escape(str(value))


def configured_webhook_url():
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("webhookUrl")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""


def webhook_url():
    url = os.environ.get("CODEX_REPORT_WEBHOOK_URL") or configured_webhook_url()
    url = url.strip()
    if url.endswith("."):
        url = url[:-1]
    return url


# --- HTML ----------------------------------------------------------------------

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #ffffff; color: #111111;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.55; }
main { max-width: 760px; margin: 0 auto; padding: 40px 20px 64px; }
header { border-bottom: 2px solid #111111; padding-bottom: 16px; margin-bottom: 8px; }
.kind { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: #555555; margin: 0 0 6px; }
h1 { font-size: 26px; line-height: 1.25; margin: 0 0 8px; }
.meta-line { color: #555555; font-size: 13px; margin: 0; }
h2 { font-size: 13px; letter-spacing: .06em; text-transform: uppercase; color: #333333;
  border-bottom: 1px solid #dddddd; padding-bottom: 6px; margin: 32px 0 12px; }
p { margin: 0 0 12px; }
.body { white-space: pre-wrap; overflow-wrap: anywhere; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; vertical-align: top; padding: 7px 10px; border-bottom: 1px solid #eeeeee; }
th { width: 34%; color: #555555; font-weight: 600; }
td { overflow-wrap: anywhere; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
ul.files { list-style: none; padding: 0; margin: 0; }
ul.files li { background: #f5f5f5; border: 1px solid #e5e5e5; border-radius: 4px;
  padding: 6px 10px; margin-bottom: 6px; overflow-wrap: anywhere; }
.muted { color: #999999; }
section.block { background: #fafafa; border-left: 3px solid #111111; padding: 12px 16px; margin-bottom: 12px; }
section.block h3 { margin: 0 0 8px; font-size: 15px; }
.title-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 0 0 8px; }
.title-row h1 { margin: 0; }
.pill { display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; line-height: 1; padding: 5px 9px; border-radius: 999px;
  border: 1px solid #111111; white-space: nowrap; }
.pill-solid { background: #111111; color: #ffffff; }
.pill-outline { background: #ffffff; color: #111111; }
.highlight { background: #f5f5f5; border-left: 5px solid #111111; padding: 14px 18px; margin: 0 0 12px; }
.plain-block { background: #fafafa; border: 1px solid #e5e5e5; padding: 14px 18px; margin: 0 0 12px; }
ol.steps { margin: 0 0 12px; padding-left: 22px; }
ol.steps li { margin-bottom: 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
.note { color: #555555; font-size: 14px; }
.compare { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.card { border: 1px solid #dddddd; padding: 12px 14px; background: #ffffff; }
.card-label { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  color: #555555; margin: 0 0 6px; }
.card-actual { border-color: #111111; }
details.env { margin-top: 32px; border: 1px solid #dddddd; padding: 0 12px; }
details.env summary { cursor: pointer; font-size: 13px; letter-spacing: .06em; text-transform: uppercase;
  color: #333333; font-weight: 600; padding: 10px 0; }
details.env[open] summary { border-bottom: 1px solid #eeeeee; margin-bottom: 4px; }
@media (max-width: 600px) { .compare { grid-template-columns: 1fr; } }
footer { margin-top: 40px; color: #777777; font-size: 12px; }
"""


def rows(pairs):
    return "\n".join(f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>" for k, v in pairs)


def text(value):
    """Escaped multi-line body text (whitespace preserved via the .body class)."""
    return html.escape(str(value or ""))


def pill(label, solid=False):
    cls = "pill pill-solid" if solid else "pill pill-outline"
    return f'<span class="{cls}">{html.escape(str(label).upper())}</span>'


def reporter_env_table(data):
    env = data.get("environment") or {}
    rep = data.get("reporter") or {}
    return "<table>" + rows([
        ("Reporter", esc(rep.get("name"))),
        ("Email", esc(rep.get("email"))),
        ("OS", esc(env.get("os"))),
        ("Claude Code", esc(env.get("claudeCodeVersion"))),
        ("Model", f'<span class="mono">{esc(env.get("model"))}</span>'),
        ("Plugin version", esc(env.get("pluginVersion"))),
        ("Harness version", esc(env.get("harnessVersion"))),
        ("Timestamp", esc(env.get("timestamp"))),
        ("Timezone", esc(env.get("timezone"))),
    ]) + "</table>"


def context_table(data, order):
    ctx = data.get("context") or {}
    labels = {"intent": "Intent", "creating": "Creating", "framework": "Framework", "piece": "Piece"}
    return "<table>" + rows([(labels[k], esc(ctx.get(k))) for k in order]) + "</table>"


def notes_html(data):
    sections = data.get("sections") or []
    if not sections:
        return ""
    blocks = "\n".join(
        f'<section class="block"><h3>{html.escape(s["heading"])}</h3>'
        f'<div class="body">{html.escape(s["body"])}</div></section>'
        for s in sections
    )
    return f"<h2>Additional notes</h2>\n{blocks}\n"


def files_html(data):
    files = data.get("relatedFiles") or []
    if not files:
        return '<p class="muted">No related files.</p>'
    return '<ul class="files">' + "".join(
        f'<li class="mono">{html.escape(p)}</li>' for p in files) + "</ul>"


def metadata_table(data, generated_at):
    return "<table>" + rows([
        ("Report type", esc(data.get("reportType"))),
        ("Slug", f'<span class="mono">{esc(data.get("slug"))}</span>'),
        ("Generated at", esc(generated_at)),
        ("Generator", '<span class="mono">codex-brand/scripts/send_report.py</span>'),
    ]) + "</table>"


def header_html(data, badge):
    env = data.get("environment") or {}
    kind = TITLES[data["reportType"]]
    return f"""<header>
<p class="kind">{kind}</p>
<div class="title-row"><h1>{html.escape(data["title"])}</h1>{badge}</div>
<p class="meta-line">{html.escape(data["brand"])} · {html.escape(data["project"])} · {esc(env.get("timestamp"))}</p>
</header>"""


def page(data, body):
    title = TITLES[data["reportType"]]
    embedded = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
<main>
{body}
<footer>Generated by the codex-brand Claude Code plugin.</footer>
</main>
<script type="application/json" id="report-data">
{embedded}
</script>
</body>
</html>
"""


def render_bug(data, generated_at):
    severity = data["severity"]
    steps = "".join(f"<li>{text(s)}</li>" for s in data["steps"])
    repro = data.get("reproducible")
    repro_html = (f'<p class="note"><strong>Reproducible:</strong> {text(repro)}</p>'
                  if isinstance(repro, str) and repro.strip() else "")
    body = f"""{header_html(data, pill(severity, solid=(severity == "blocking")))}

<h2>Summary</h2>
<p class="body">{text(data["summary"])}</p>

<h2>What the user wanted</h2>
{context_table(data, ("intent", "creating", "framework", "piece"))}

<h2>Where it failed</h2>
<div class="highlight body">{text(data["friction"])}</div>

<h2>Steps to reproduce</h2>
<ol class="steps">{steps}</ol>
{repro_html}

<h2>Expected vs actual</h2>
<div class="compare">
<div class="card"><p class="card-label">Expected</p><div class="body">{text(data["expected"])}</div></div>
<div class="card card-actual"><p class="card-label">Actual</p><div class="body">{text(data["actual"])}</div></div>
</div>

{notes_html(data)}
<h2>Related files</h2>
{files_html(data)}

<h2>Reporter &amp; environment</h2>
{reporter_env_table(data)}

<h2>Metadata</h2>
{metadata_table(data, generated_at)}
"""
    return page(data, body)


def render_feedback(data, generated_at):
    body = f"""{header_html(data, pill(data["area"]))}

<h2>Summary</h2>
<p class="body">{text(data["summary"])}</p>

<h2>What they were doing</h2>
<p class="body">{text(data["doing"])}</p>
{context_table(data, ("framework", "piece", "intent", "creating"))}

<h2>What got in the way</h2>
<div class="plain-block body">{text(data["painPoint"])}</div>

<h2>How it should work</h2>
<div class="highlight body">{text(data["proposal"])}</div>

<h2>Expected gain</h2>
<p class="body">{text(data["gain"])}</p>

{notes_html(data)}
<h2>Related files</h2>
{files_html(data)}

<details class="env"><summary>Reporter &amp; environment</summary>
{reporter_env_table(data)}
</details>

<h2>Metadata</h2>
{metadata_table(data, generated_at)}
"""
    return page(data, body)


def render_html(data, generated_at):
    renderer = render_bug if data["reportType"] == "bug" else render_feedback
    return renderer(data, generated_at)


# --- Sending -------------------------------------------------------------------

def build_payload(data, filename, html_text):
    return {
        "reportType": data["reportType"],
        "brand": data["brand"],
        "reporterName": (data.get("reporter") or {}).get("name", ""),
        "summaryText": summary_text(data),
        "attachments": [{"name": filename, "contentType": "text/html", "content": html_text}],
    }


def post(payload):
    url = webhook_url()
    if not url:
        raise SendError("webhook not configured (set CODEX_REPORT_WEBHOOK_URL)")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        reason = f"HTTP {exc.code}"
        if exc.code == 401:
            reason += " (unauthorized: check for a trailing dot in the URL or an expired signature)"
        elif exc.code == 403:
            reason += " (forbidden: the network/proxy must allow *.powerplatform.com)"
        raise SendError(reason) from None
    except urllib.error.URLError as exc:
        reason = f"network error: {exc.reason}"
        if "403" in str(exc.reason):
            reason += " (the network/proxy must allow *.powerplatform.com)"
        raise SendError(reason) from None
    except (TimeoutError, OSError) as exc:
        raise SendError(f"network error: {exc.__class__.__name__}") from None
    if status not in (200, 202):
        raise SendError(f"unexpected HTTP {status}")


def read_embedded(html_text):
    match = re.search(r'<script type="application/json" id="report-data">\s*(.*?)\s*</script>',
                      html_text, re.S)
    if not match:
        return None
    return json.loads(match.group(1).replace("<\\/", "</"))


def retry_pending():
    if not PENDING_DIR.is_dir():
        return
    files = sorted(PENDING_DIR.glob("*.html"))
    if not files:
        return
    sent = failed = 0
    for path in files:
        try:
            html_text = path.read_text(encoding="utf-8")
            data = read_embedded(html_text)
            if not data or validate(data):
                raise SendError("embedded report data missing or invalid")
            post(build_payload(data, path.name, html_text))
            path.unlink()
            sent += 1
        except (SendError, ValueError, OSError):
            failed += 1
    print(f"Pending reports: {sent} resent, {failed} still pending.")


def move_to_pending(html_path):
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    target = PENDING_DIR / html_path.name
    shutil.move(str(html_path), str(target))
    return target.resolve()


# --- Main ----------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Render and send a Codex bug report / feedback.")
    parser.add_argument("--data", required=True, help="path to report-data.json")
    parser.add_argument("--dry-run", action="store_true", help="render only, no POST, keep files")
    parser.add_argument("--out", help="output directory for the HTML (default: the data file's directory)")
    args = parser.parse_args(argv)

    data_path = Path(args.data).expanduser().resolve()
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: data file not found: {data_path}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        print(f"ERROR: cannot read report data: {exc}", file=sys.stderr)
        return 1

    errors = validate(data)
    if errors:
        print("ERROR: invalid report data:\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1

    now = dt.datetime.now().astimezone()
    filename = f"{data['reportType']}-{now:%Y%m%d-%H%M%S}-{slugify(data['brand'])}-{slugify(data['slug'])}.html"
    out_dir = Path(args.out).expanduser().resolve() if args.out else data_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / filename
    html_text = render_html(data, now.isoformat(timespec="seconds"))
    html_path.write_text(html_text, encoding="utf-8")

    payload = build_payload(data, filename, html_text)
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    if args.dry_run:
        payload_path = out_dir / (filename[:-5] + ".payload.json")
        payload_path.write_bytes(payload_bytes)
        print("DRY RUN: no request sent.")
        print(f"HTML: {html_path}")
        print(f"Payload: {payload_path} ({len(payload_bytes)} bytes)")
        print(f"REPORT_FILE={filename}")
        return 0

    retry_pending()

    try:
        post(payload)
    except SendError as exc:
        pending = move_to_pending(html_path)
        print(f"Send failed: {exc}")
        print(f"REPORT_PENDING={pending}")
        return 2

    html_path.unlink(missing_ok=True)
    data_path.unlink(missing_ok=True)
    for folder in {out_dir, data_path.parent}:
        try:
            folder.rmdir()  # only removes it if now empty (e.g. the mktemp dir)
        except OSError:
            pass
    print(f"REPORT_SENT={filename}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
