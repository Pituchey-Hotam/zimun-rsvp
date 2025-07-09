import functions_framework
from pywa import WhatsApp, utils, types
from dotenv import load_dotenv
import os

load_dotenv()

wa = WhatsApp(
    phone_id=os.environ['WABA_PHONE_ID'],  # The phone id you got from the API Setup
    token=os.environ['WABA_TOKEN'],  # The token you got from the API Setup,
    server=None,
    verify_token=os.environ['WABA_WEBHOOK_VERIFY']
)

@wa.on_message
def hello(_: WhatsApp, msg: types.Message):
    msg.react('👋')
    msg.reply(f'Hello {msg.from_user.name}!')

@functions_framework.http
def waba_webhook(request):
    if request.method == "GET":
        return wa.webhook_challenge_handler(
            vt=request.args.get(utils.HUB_VT),
            ch=request.args.get(utils.HUB_CH),
        )
    elif request.method == "POST":
        return wa.webhook_update_handler(
            update=request.data,
            hmac_header=request.headers.get(utils.HUB_SIG),
        )