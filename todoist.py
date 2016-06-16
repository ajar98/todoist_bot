from flask import Flask
from flask import request
import os

app = Flask(__name__)

APP_TOKEN = os.environ['FB_ACCESS_TOKEN']
FB_MESSAGES_ENDPOINT = "https://graph.facebook.com/v2.6/me/messages"


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET":
        if request.args.get('hub.verify_token') == 'todoist_is_my_fave':
            return request.args.get('hub.challenge')
        else:
            return 'Wrong validation token'
    else:
        if request.method == "POST":
            data = json.loads(request.data)['entry'][0]['messaging']
            for m in data:
                resp_id = m['sender']['id']
                resp_mess = {
                    'recipient': {
                        'id': resp_id
                    },
                    'message': {
                        'text': m['message']['text'],
                    }
                }
                fb_response = requests.post(
                    FB_MESSAGES_ENDPOINT,
                    params={"access_token": APP_TOKEN},
                    data=json.dumps(resp_mess),
                    headers={'content-type': 'application/json'})
        return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
