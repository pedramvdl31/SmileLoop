# coding: utf-8
"""
SmileLoop – Email Service (AWS SES via boto3)

Sends a transactional "Your preview is ready" email after video generation.
Uses send_raw_email to set List-Unsubscribe and Reply-To headers,
which significantly helps inbox placement.
"""

import traceback
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from webapp.config import (
    APP_URL,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_SES_REGION,
    EMAIL_FROM_ADDRESS,
    EMAIL_FROM_NAME,
)


def _get_ses_client():
    """Create a boto3 SES client. Returns None if not configured."""
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        return None
    try:
        import boto3
        return boto3.client(
            "ses",
            region_name=AWS_SES_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
    except Exception as e:
        print(f"WARNING: Could not create SES client: {e}")
        return None


def send_preview_ready_email(
    to_email: str,
    job_id: str,
    preview_url: Optional[str] = None,
) -> bool:
    """
    Send a "Your video preview is ready" transactional email.

    Args:
        to_email: Recipient email address.
        job_id: The job ID (used to build the view link).
        preview_url: Optional direct preview URL (not used currently).

    Returns:
        True if sent successfully, False otherwise.
    """
    client = _get_ses_client()
    if not client:
        print(f"SES not configured — skipping email to {to_email} for job {job_id}")
        return False

    view_link = f"{APP_URL}/?job_id={job_id}"
    unsub_link = f"{APP_URL}/unsubscribe?email={to_email}"
    from_addr = f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>"

    subject = "Your SmileLoop video preview is ready"

    # ── Plain-text body (important for spam score) ──────────────────────
    text_body = f"""\
Hi there,

Your SmileLoop video preview is ready to view.

We animated your photo and created a short video clip. You can
watch the preview here:

  {view_link}

If you like it, you can get the full-resolution version without
the watermark from the same page.

Thanks for using SmileLoop!

--
SmileLoop by Bloop Entertainment Inc.
Toronto, ON, Canada
This is a one-time transactional email for a video you requested.
Unsubscribe: {unsub_link}"""

    # ── HTML body (clean, high text ratio, no spammy language) ─────────
    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your SmileLoop Preview</title>
</head>
<body style="margin:0; padding:0; background-color:#f5f5f5; font-family:Helvetica, Arial, sans-serif; color:#333333;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="540" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:8px;">
          <!-- Header -->
          <tr>
            <td style="padding:28px 32px 0; text-align:center;">
              <span style="font-size:22px; font-weight:700; color:#222222;">SmileLoop</span>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:24px 32px 28px;">
              <p style="margin:0 0 14px; font-size:16px; line-height:1.5; color:#333333;">
                Hi there,
              </p>
              <p style="margin:0 0 14px; font-size:16px; line-height:1.5; color:#333333;">
                Your video preview is ready to view. We animated your photo
                and created a short video clip.
              </p>
              <p style="margin:0 0 24px; font-size:16px; line-height:1.5; color:#333333;">
                Click the link below to watch it:
              </p>
              <!-- CTA -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center" style="padding-bottom:24px;">
                    <a href="{view_link}"
                       style="display:inline-block; background-color:#e8734a; color:#ffffff; text-decoration:none; font-weight:600; font-size:16px; padding:12px 32px; border-radius:6px;">
                      View My Preview
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0; font-size:14px; line-height:1.5; color:#666666;">
                If you like the preview, you can get the full-resolution
                version without the watermark from the same page.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:20px 32px; border-top:1px solid #eeeeee; text-align:center;">
              <p style="margin:0 0 6px; font-size:12px; color:#999999; line-height:1.5;">
                SmileLoop by Bloop Entertainment Inc. &middot; Toronto, ON, Canada
              </p>
              <p style="margin:0; font-size:12px; color:#999999; line-height:1.5;">
                This is a one-time email for a video you requested.
                <a href="{unsub_link}" style="color:#999999;">Unsubscribe</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    # ── Build MIME message with proper headers ─────────────────────────
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Reply-To"] = EMAIL_FROM_ADDRESS
    msg["List-Unsubscribe"] = f"<{unsub_link}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg["X-SES-MESSAGE-TAGS"] = "purpose=transactional"

    # Attach plain text first (fallback), then HTML
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        response = client.send_raw_email(
            Source=from_addr,
            Destinations=[to_email],
            RawMessage={"Data": msg.as_string()},
        )
        message_id = response.get("MessageId", "unknown")
        print(f"Email sent to {to_email} for job {job_id} (MessageId: {message_id})")
        return True
    except Exception as e:
        print(f"ERROR: Failed to send email to {to_email}: {e}")
        traceback.print_exc()
        return False
