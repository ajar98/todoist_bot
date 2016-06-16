from flask import Flask
from flask import request
import json
import requests
from client import TodoistClient

app = Flask(__name__)

APP_TOKEN = "EAAPGnoxDIZC8BAGJC26eKJnuOsHO95ZCqmDvxOY0OoLHUSjecSsZBUObB\
PYjpLhLzjjv8MdWrSvsYZAAkG6XO3Vx9S54OYHZCFe7nV04pBBhyYK8VPwehszO44W57l6s\
EbTemYEO4cesUW19ZB2GxAZB1CJuaguPfqlmrtLCzlplgZDZD"
FB_MESSAGES_ENDPOINT = "https://graph.facebook.com/v2.6/me/messages"


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET":
        if request.args.get('hub.verify_token') == 'todoist_is_my_fave':
            return request.args.get('hub.challenge')
        else:
            return 'Wrong validation token'
    else:
        if request.method == 'POST':
            data = json.loads(request.data)['entry'][0]['messaging']
            for m in data:
                print m
                if 'message' in m and 'text' in m['message']:
                    sender_id = m['sender']['id']
                    message = m['message']['text']
                    resp_mess = {
                        'recipient': {
                            'id': sender_id
                        },
                        'message': {
                            'text': '{0} to you!'.format(message),
                        }
                    }
                    fb_response = requests.post(
                        FB_MESSAGES_ENDPOINT,
                        params={"access_token": APP_TOKEN},
                        data=json.dumps(resp_mess),
                        headers={'content-type': 'application/json'})
                    if not fb_response.ok:
                        print 'Not ok. %s: %s' % (
                            fb_response.status_code,
                            fb_response.text
                        )
        return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
