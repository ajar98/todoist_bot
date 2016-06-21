from flask import Flask
from flask import request, abort
import json
import requests
import urllib
import requests.auth
import os
from client import TodoistClient
from uuid import uuid4

app = Flask(__name__)

FB_MESSAGES_ENDPOINT = "https://graph.facebook.com/v2.6/me/messages"
OAUTH_CODE_ENDPOINT = "https://todoist.com/oauth/authorize"
OAUTH_ACCESS_TOKEN_ENDPOINT = "https://todoist.com/oauth/access_token"
REDIRECT_URI = "http://pure-hamlet-63323.herokuapp.com/todoist_callback"


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
                    if not(sender_id in os.environ):
                        get_access_token(sender_id)
                    if sender_id in os.environ:
                        bot_responses = get_bot_responses(sender_id, message)
                        for bot_response in bot_responses:
                            print bot_response
                            send_FB_text(sender_id, bot_response)
        return "OK", 200


def get_bot_responses(sender_id, message):
    tc = TodoistClient(os.environ[sender_id])
    if message.lower() == 'tasks':
        return ['* {0} (Due {1})'.format(
            task['content'],
            task['date_string']) for task in tc.get_this_week_tasks()]
    elif 'write task' in message:
        task_name = message.split('\"')[1]
        date_string = message.split('\"')[3]
        tc.write_task(task_name, 'Inbox', date_string=date_string)
        return ['Task written.']
    else:
        return ['Type \'tasks\' to get your tasks for the next week. \
        Type \'write task \"<task_name>\" due \"<date_string>\"\'']


def get_access_token(sender_id):
    os.environ[sender_id] = 'temp'
    send_FB_button(
        sender_id,
        'Looks like you haven\'t authorized Todoist.',
        'Authorize now',
        '{0}?{1}'.format(
            OAUTH_CODE_ENDPOINT,
            urllib.urlencode(
                {
                    'client_id': os.environ['TODOIST_CLIENT_ID'],
                    'scope': 'data:read_write,data:delete',
                    'redirect_uri': REDIRECT_URI,
                    'state': uuid4()
                }
            )
        )
    )


@app.route('/todoist_callback')
def todoist_callback(methods=['GET']):
    if request.method == 'GET':
        error = request.args.get('error', '')
        if error:
            return "Error: " + error
        state = request.args.get('state', '')
        code = request.args.get('code')
        # We'll change this next line in just a moment
        access_token = get_token(code)
        print "Access token: {0}".format(access_token)
        for key, value in os.environ.items():
            if value == 'temp':
                os.environ[key] = access_token
        return "success" if access_token else "failure"


def get_token(code):
    post_data = {
        'client_id': os.environ['TODOIST_CLIENT_ID'],
        'client_secret': os.environ['TODOIST_CLIENT_SECRET'],
        'code': code,
        'redirect_uri': REDIRECT_URI
    }
    response = requests.post(
        OAUTH_ACCESS_TOKEN_ENDPOINT,
        data=post_data
    )
    token_json = response.json()
    return token_json["access_token"]


def send_FB_message(sender_id, message):
    fb_response = requests.post(
        FB_MESSAGES_ENDPOINT,
        params={'access_token': os.environ['FB_APP_TOKEN']},
        data=json.dumps(
            {
                'recipient': {
                    'id': sender_id
                },
                'message': message
            }
        ),
        headers={'content-type': 'application/json'})
    if not fb_response.ok:
        print "Not OK: {0}: {1}".format(
            fb_response.status_code,
            fb_response.text
        )
    else:
        print "OK: {0}".format(200)


def send_FB_text(sender_id, text):
    return send_FB_message(
        sender_id,
        {
            'text': text
        }
    )


def send_FB_button(sender_id, text, button_text, web_url):
    return send_FB_message(
        sender_id,
        {
            'attachment': {
                'type': 'template',
                'payload': {
                    'template_type': 'button',
                    'text': text,
                    'buttons': [
                        {
                            'type': 'web_url',
                            'title': button_text,
                            'url': web_url
                        }
                    ]
                }
            }
        }
    )


def updateDict(old_dict, update):
    new_dict = old_dict
    new_dict.update(update)
    return new_dict


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
