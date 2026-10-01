import html
import json
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .domain import canonical_url


def render_digest(payload):
    label = "FIXTURE — NOT LIVE NEWS" if payload["mode"] == "fixture" else "AI news digest"
    title = f"{label} · {payload['date']}"
    plain = [title, "", payload["greeting"], payload["introduction"], ""]
    body = [f"<h1>{html.escape(title)}</h1>", f"<p>{html.escape(payload['greeting'])}</p>", f"<p>{html.escape(payload['introduction'])}</p>"]
    if not payload["articles"]:
        plain.append("No articles were published in the selected window.")
        body.append("<p>No articles were published in the selected window.</p>")
    for item in payload["articles"]:
        url = canonical_url(item["url"])
        plain.extend([f"## {item['title']}", item["summary"], f"Source: {item['source']} · {item['published_at']}", f"Why: {item['reason']}", url, ""])
        body.append(f"<section><h2><a href=\"{html.escape(url, quote=True)}\">{html.escape(item['title'])}</a></h2><p>{html.escape(item['summary'])}</p><p class=\"meta\">{html.escape(item['source'])} · {html.escape(item['published_at'])}</p><p><strong>Why this matters:</strong> {html.escape(item['reason'])}</p></section>")
    html_doc = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>AI news digest</title><style>body{max-width:720px;margin:40px auto;padding:0 24px;font:17px/1.6 system-ui;color:#172033;background:#f7f8fb}h1{font-size:28px}h2{font-size:21px;line-height:1.4}section{background:white;border:1px solid #dce1ea;border-radius:12px;padding:20px;margin:20px 0}a{color:#164ac5}.meta{font-size:13px;color:#647086}</style></head><body>" + "".join(body) + "</body></html>"
    return title, "\n".join(plain), html_doc


def email_message(payload, sender="news@example.invalid", recipient="reader@example.invalid"):
    subject, text, html_doc = render_digest(payload)
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, sender, recipient
    message["Message-ID"] = f"<{payload['id']}@news-aggregator.invalid>"
    message.set_content(text)
    message.add_alternative(html_doc, subtype="html")
    return message


def write_preview(payload, directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    _, text, html_doc = render_digest(payload)
    stem = path / payload["id"]
    files = {"html": str(stem.with_suffix(".html")), "markdown": str(stem.with_suffix(".md")), "json": str(stem.with_suffix(".json")), "eml": str(stem.with_suffix(".eml"))}
    Path(files["html"]).write_text(html_doc, encoding="utf-8")
    Path(files["markdown"]).write_text(text, encoding="utf-8")
    Path(files["json"]).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(files["eml"]).write_bytes(email_message(payload).as_bytes())
    return files


def validate_delivery(payload, config, delivery):
    if delivery == "preview":
        return
    host = config["host"]
    if delivery == "sink":
        if host not in {"localhost", "127.0.0.1", "::1", "mailpit"} or config.get("username"):
            raise ValueError("Sink delivery requires local Mailpit without authentication")
        sender, recipient = "news@example.invalid", "reader@example.invalid"
    elif delivery == "real":
        if not config.get("allow_real"):
            raise ValueError("Real delivery requires ALLOW_REAL_EMAIL=true and --send real after explicit recipient authorization")
        if payload["mode"] == "fixture":
            raise ValueError("Fixture data cannot be sent to real recipients")
        if not config.get("starttls"):
            raise ValueError("Real SMTP delivery requires STARTTLS")
        sender, recipient = config["sender"], config["recipient"]
        if sender.endswith(".invalid") or recipient.endswith(".invalid"):
            raise ValueError("Configure real SMTP_FROM and SMTP_TO addresses")
    else:
        raise ValueError("Unknown delivery mode")
    return sender, recipient


def send_email(payload, config, delivery):
    addresses = validate_delivery(payload, config, delivery)
    if addresses is None:
        return
    sender, recipient = addresses
    host, port = config["host"], config["port"]
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if config.get("starttls"):
            smtp.starttls(context=ssl.create_default_context())
        if config.get("username"):
            smtp.login(config["username"], config["password"])
        smtp.send_message(email_message(payload, sender, recipient))
