import logging
import os
import sys
import functions_framework
import google.auth
import google.cloud.logging

from pywa import WhatsApp, utils
from dotenv import load_dotenv

from guests import GuestsManager
from bot import RSVPBot

load_dotenv(override=True)
# Configuration
WABA_PHONE_ID = os.getenv("WABA_PHONE_ID")
WABA_TOKEN = os.getenv("WABA_TOKEN")
WABA_WEBHOOK_VERIFY = os.getenv("WABA_WEBHOOK_VERIFY")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WORKSHEET_ID = os.getenv("WORKSHEET_ID")
INVITATION_URL = os.getenv("INVITATION_URL")
LOCAL_TESTING = os.getenv("LOCAL_TESTING")

if LOCAL_TESTING:
    credentials = GuestsManager.creds_from_file("service_account.json")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)
else:
    client = google.cloud.logging.Client()
    client.setup_logging(log_level = logging.DEBUG)

    credentials, _ = google.auth.default(
        scopes=[
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
    )

wa = WhatsApp(
    phone_id=WABA_PHONE_ID,
    token=WABA_TOKEN,
    server=None,
    verify_token=WABA_WEBHOOK_VERIFY
)

guests = GuestsManager(
    credentials,
    SPREADSHEET_ID,
    WORKSHEET_ID
)

logging.debug(guests.get_all_guests())

# Initialize bot
bot = RSVPBot(guests, wa, INVITATION_URL)

if LOCAL_TESTING:
    bot.send_invitations()
else:
    @functions_framework.http
    def waba_webhook(request):
        logging.debug(f"{request.method} {request.path} <{request.data.decode("utf8")}>")
        if request.method == "GET":
            if request.path == "/stage_invites":
                guests = bot.guests.get_uninvited_guests()
                return "<br/>".join([g.display_name for g in guests])
            if request.path == "/send_invites":
                bot.send_invitations()
                return "Sent"
            else:
                return wa.webhook_challenge_handler(
                    vt=request.args.get(utils.HUB_VT),
                    ch=request.args.get(utils.HUB_CH),
                )
        elif request.method == "POST":
            return wa.webhook_update_handler(
                update=request.data,
                hmac_header=request.headers.get(utils.HUB_SIG),
            )