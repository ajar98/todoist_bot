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
TOKEN = 'e5d57a2cbb3a10c236c78eba3d578e18f875a4ee'


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
                if ('message' in m) and ('text' in m['message']):
                    sender_id = m['sender']['id']
                    message = m['message']['text']
                    bot_responses = get_bot_responses(message)
                    for bot_response in bot_responses:
                        print bot_response
                        resp_mess = {
                            'recipient': {
                                'id': sender_id
                            },
                            'message': {
                                'text': bot_response,
                            }
                        }
                        fb_response = requests.post(
                            FB_MESSAGES_ENDPOINT,
                            params={'access_token': APP_TOKEN},
                            data=json.dumps(resp_mess),
                            headers={'content-type': 'application/json'})
                        if not fb_response.ok:
                            print 'Not ok. %s: %s' % (
                                fb_response.status_code,
                                fb_response.text
                            )
        return "OK", 200


def get_bot_responses(message):
    tc = TodoistClient(TOKEN)
    if message == 'tasks':
        return ['* {0}'.format(task) for task in tc.get_this_week_tasks()]
    elif 'write task' in message:
        task_name = message.split('\"')[1]
        date_string = message.split('\"')[3]
        tc.write_task(task_name, 'Inbox', date_string=date_string)
        return ['Task written.']
    else:
        return ['Type \'tasks\' to get your tasks for the next week. \
        Type \'write task \"<task_name>\" due \"<date_string>\"\'']


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
