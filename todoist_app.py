from flask import Flask
from flask import request, abort
import json
import requests
import urllib
import requests.auth
import os
from client import TodoistClient
from uuid import uuid4
from pymongo import MongoClient
from dateutil.parser import parse

FB_MESSAGES_ENDPOINT = 'https://graph.facebook.com/v2.6/me/messages'
OAUTH_CODE_ENDPOINT = 'https://todoist.com/oauth/authorize'
OAUTH_ACCESS_TOKEN_ENDPOINT = 'https://todoist.com/oauth/access_token'
REDIRECT_URI = 'http://pure-hamlet-63323.herokuapp.com/todoist_callback'


def connect():
    connection = MongoClient('ds021434.mlab.com', 21434)
    handle = connection['todoist_access_tokens']
    handle.authenticate('chatbot', 'weaboo')
    return handle


app = Flask(__name__)
handle = connect()


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == 'todoist_is_my_fave':
            return request.args.get('hub.challenge')
        else:
            return 'Wrong validation token'
    else:
        if request.method == 'POST':
            data = json.loads(request.data)['entry'][0]['messaging']
            for event in data:
                print event
                if 'sender' in event and 'message' in event:
                    sender_id = event['sender']['id']
                    message = event['message']['text']
                    if handle.access_tokens.find(
                        {'sender_id': sender_id}
                    ).count() == 0:
                        get_access_token(sender_id)
                    sender_id_matches = [x for x in handle.access_tokens.find(
                        {'sender_id': sender_id})]
                    if sender_id_matches:
                        access_token = sender_id_matches[0]['access_token']
                        tc = TodoistClient(access_token)
                        if ('message' in m) and ('text' in m['message']):
                            if 'tasks' in message.lower():
                                if ' in ' in message.lower():
                                    project_name = message.lower().split(' in ')[1]
                                    project_tasks = tc.get_project_tasks()
                                    if type(project_tasks) is list:
                                        if len(project_tasks) > 0:
                                            send_tasks(sender_id, tc.get_project_tasks())
                                        else:
                                            send_FB_text(sender_id, 'No tasks in this project.')
                                    else:
                                        send_FB_text(sender_id, 'Not a valid project.')
                                elif ' up to ' in message.lower():
                                    date_string = message.lower().split(' up to ')[1]
                                    date = None
                                    try:
                                        date = parse(date_string)
                                    except ValueError:
                                        send_FB_text(
                                            sender_id,
                                            'Date text not recognized. Try using actual dates.'
                                        )
                                    if date:
                                        send_tasks(sender_id, tc.get_tasks_up_to_date(date))
                                else:
                                    send_tasks(sender_id, tc.get_this_week_tasks())
                            elif ' due ' in message:
                                write_task(sender_id, tc, message)
                            else:
                                generic_response(sender_id)
                        if 'postback' in m:
                            payload = m['postback']['payload']
                            if payload == 'tasks':
                                send_tasks(sender_id, tc.get_this_week_tasks())
                            if payload == 'write':
                                send_write_request(sender_id)
                            if 'task_id' in payload:
                                complete_task(sender_id, tc, payload.split(':')[1])
        return 'OK', 200


def complete_task(sender_id, tc, task_id):
    task_id = payload.split(':')[1]
    print task_id
    tc.complete_task(task_id)
    send_FB_text(sender_id, 'Task completed.')


def send_tasks(sender_id, tasks):
    for task in tasks:
        send_FB_buttons(
            sender_id,
            '* {0} (Due {1})'.format(
                task['content'],
                task['date_string']
            ),
            [
                {
                    'type': 'postback',
                    'title':
                    'Complete',
                    'payload': '{0}:{1}'.format(
                        'task_id',
                        task['id']
                    )
                },
            ]
        )


def send_write_request(sender_id):
    send_FB_text(
        sender_id,
        'Enter your task as follows: <Task Name> due <Date string>. Enter \'never\' if there is no due date.'
    )


def write_task(sender_id, tc, message):
    task_name = message.split(' due ')[0]
    date_string = message.split(' due ')[1]
    if date_string == 'never':
        tc.write_task(
            task_name,
            'Inbox',
        )
    else:
        tc.write_task(
            task_name,
            'Inbox',
            date_string=date_string
        )
    send_FB_text(sender_id, 'Task written.')


def generic_response(sender_id):
    send_FB_buttons(
        sender_id,
        'Hi there! Would you like view your tasks or write tasks? \
        You can also view tasks by typing \'tasks\'. \
        You can view tasks up to a certain date by typing \'tasks up to <date_string>\' \
        You can view tasks in a specific project by typing \'tasks in <project_name>\'',
        [
            {
                'type': 'postback',
                'title': 'View my tasks',
                'payload': 'tasks'
            },
            {
                'type': 'postback',
                'title': 'Write tasks',
                'payload': 'write'
            }
        ],
    )


def get_access_token(sender_id):
    handle.access_tokens.insert(
        {
            'sender_id': sender_id,
            'access_token': 'temp'
        }
    )
    send_FB_buttons(
        sender_id,
        'Looks like you haven\'t authorized Todoist.',
        [
            {
                'type': 'web_url',
                'title': 'Authorize now',
                'url': '{0}?{1}'.format(
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
            }
        ],
    )


@app.route('/todoist_callback')
def todoist_callback(methods=['GET']):
    if request.method == 'GET':
        error = request.args.get('error', '')
        if error:
            return 'Error: ' + error
        state = request.args.get('state', '')
        code = request.args.get('code')
        # We'll change this next line in just a moment
        access_token = get_token(code)
        print 'Access token: {0}'.format(access_token)
        handle.access_tokens.update(
            {'access_token': 'temp'},
            {
                '$set': {
                    'access_token': access_token
                }
            }
        )
        return 'success' if access_token and \
            handle.access_tokens.find(
                {'access_token': access_token}
            ).count() else 'failure'


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
    return token_json['access_token']


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
        print 'Not OK: {0}: {1}'.format(
            fb_response.status_code,
            fb_response.text
        )
    else:
        print 'OK: {0}'.format(200)


def send_FB_text(sender_id, text):
    return send_FB_message(
        sender_id,
        {
            'text': text
        }
    )


def send_FB_buttons(sender_id, text, buttons):
    return send_FB_message(
        sender_id,
        {
            'attachment': {
                'type': 'template',
                'payload': {
                    'template_type': 'button',
                    'text': text,
                    'buttons': buttons
                }
            }
        }
    )


def updateDict(old_dict, update):
    new_dict = old_dict
    new_dict.update(update)
    return new_dict


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
