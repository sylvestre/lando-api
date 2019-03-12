# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

from landoapi.celery import celery

TRANSPLANT_FAILURE_EMAIL_TEMPLATE = """
Your request to land {phab_revision_id} failed.

See {lando_revision_url} for details.

Reason:
{reason}
""".strip()

logger = logging.getLogger(__name__)


@celery.task(
    # Auto-retry for IOErrors from the SMTP socket connection. Don't log
    # stack traces.  All other exceptions will log a stack trace and cause an
    # immediate job failure without retrying.
    autoretry_for=(IOError,),
    # Seconds to wait between retries.
    default_retry_delay=60,
    # Retry sending the notification for three days.  This is the same effort
    # that SMTP servers use for their outbound mail queues.
    max_retries=60 * 24 * 3,
    # Don't store the success or failure results.
    ignore_result=True,
    # Don't ack jobs until the job is complete. This should only come up if a worker
    # dies suddenly in the middle of an email job.  If it does die then it is possible
    # for the user to get two emails (harmless), which is better than them receiving
    # no emails.
    acks_late=True,
)
def send_landing_failure_email(recipient_email: str, revision_id: str, error_msg: str):
    """Tell a user that the Transplant service couldn't land their code.

    Args:
        recipient_email: The email of the user receiving the failure notification.
        revision_id: The Phabricator Revision ID that failed to land. e.g. D12345
        error_msg: The error message returned by the Transplant service.
    """
    if current_app.config.get("MAIL_SUPPRESS_SEND"):
        logger.warning(
            f"Email sending suppressed: application config has disabled "
            f"all mail sending (recipient was: {recipient_email})"
        )
        return

    whitelist = current_app.config.get("MAIL_RECIPIENT_WHITELIST")
    if whitelist and recipient_email not in whitelist:
        logger.info(
            f"Email sending suppressed: recipient {recipient_email} not found in "
            f"MAIL_RECIPIENT_WHITELIST"
        )
        return

    with smtplib.SMTP(
        current_app.config.get("MAIL_SERVER"), current_app.config.get("MAIL_PORT")
    ) as smtp:
        smtp.send_message(
            make_failure_email(
                recipient_email,
                revision_id,
                error_msg,
                current_app.config["LANDO_UI_URL"],
            )
        )

    logger.info(f"Notification email sent to {recipient_email}")


def make_failure_email(
    recipient_email: str, revision_id: str, error_msg: str, lando_ui_url: str
) -> EmailMessage:
    """Build a failure EmailMessage.

    Args:
        recipient_email: The email of the user receiving the failure notification.
        revision_id: The Phabricator Revision ID that failed to land. e.g. D12345
        error_msg: The error message returned by the Transplant service.
        lando_ui_url: The base URL of the Lando website. e.g. https://lando.test
    """
    msg = EmailMessage()
    msg["From"] = "mozphab-prod@mozilla.com"
    msg["To"] = recipient_email
    msg["Subject"] = f"Lando: Landing of {revision_id} failed!"
    lando_revision_url = f"{lando_ui_url}/{revision_id}/"
    msg.set_content(
        TRANSPLANT_FAILURE_EMAIL_TEMPLATE.format(
            phab_revision_id=revision_id,
            lando_revision_url=lando_revision_url,
            reason=error_msg,
        )
    )
    return msg
