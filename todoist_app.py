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
from datetime import timedelta, datetime
from webob import Response
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.mongodb import MongoDBJobStore

FB_MESSAGES_ENDPOINT = 'https://graph.facebook.com/v2.6/me/messages'
OAUTH_CODE_ENDPOINT = 'https://todoist.com/oauth/authorize'
OAUTH_ACCESS_TOKEN_ENDPOINT = 'https://todoist.com/oauth/access_token'
REDIRECT_URI = 'http://pure-hamlet-63323.herokuapp.com/todoist_callback'
MONGO_DB_TOKENS_DATABASE = 'todoist_access_tokens'
MONGO_DB_TOKENS_ENDPOINT = 'ds021434.mlab.com'
MONGO_DB_TOKENS_PORT = 21434
MONGO_DB_JOBS_DATABASE = 'apscheduler'
MONGO_DB_JOBS_ENDPOINT = 'ds011715.mlab.com'
MONGO_DB_JOBS_PORT = 11715
MONGO_DB_JOBS_URL = 'mongodb://{0}:{1}@{2}:{3}/{4}'.format(
    os.environ['MONGO_DB_USERNAME'],
    os.environ['MONGO_DB_PWD'],
    MONGO_DB_JOBS_ENDPOINT,
    MONGO_DB_JOBS_PORT,
    MONGO_DB_JOBS_DATABASE
)


REMINDER_OFFSET = 30


def connect():
    connection = MongoClient(
        MONGO_DB_TOKENS_ENDPOINT,
        MONGO_DB_TOKENS_PORT
    )
    handle = connection[MONGO_DB_TOKENS_DATABASE]
    handle.authenticate(
        os.environ['MONGO_DB_USERNAME'],
        os.environ['MONGO_DB_PWD']
    )
    return handle


app = Flask(__name__)
app.config['DEBUG'] = True
handle = connect()
scheduler = BackgroundScheduler(jobstores={
    'default': MongoDBJobStore(host=MONGO_DB_JOBS_URL)
})


@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get('hub.verify_token') == 'todoist_is_my_fave':
            return request.args.get('hub.challenge')
        else:
            return 'Wrong validation token'
    elif request.method == 'POST':
        data = json.loads(request.data)['entry'][0]['messaging']
        for event in data:
            # check if the event was sent by someone
            if 'sender' in event:
                sender_id = event['sender']['id']
                # get Todoist access token if there is none in MongoDB
                if handle.bot_users.find(
                    {'sender_id': sender_id}
                ).count() == 0:
                    get_access_token(sender_id)
                sender_id_matches = [x for x in handle.bot_users.find(
                    {'sender_id': sender_id})]
                if sender_id_matches:
                    access_token = sender_id_matches[0]['access_token']
                    tc = TodoistClient(access_token)
                    # add user_id to Mongo object to handle live notifications
                    if not 'user_id' in [x for x in handle.bot_users.find(
                        {'access_token': access_token}
                    )][0]:
                        handle.bot_users.update(
                            {'access_token': access_token},
                            {
                                '$set': {
                                    'user_id': tc.user_id
                                }
                            }
                        )
                    if 'message' in event and 'text' in event['message']:
                        message = event['message']['text']
                        if 'tasks' in message.lower():
                            # return tasks in project
                            if ' in ' in message.lower():
                                project_name = message.lower().split(
                                    ' in '
                                )[1]
                                project_tasks = tc.get_project_tasks(
                                    project_name
                                )
                                if type(project_tasks) is list:
                                    if len(project_tasks) > 0:
                                        send_tasks(
                                            sender_id,
                                            project_tasks
                                        )
                                    else:
                                        send_FB_text(
                                            sender_id,
                                            'No tasks in this project.'
                                        )
                                else:
                                    send_FB_text(
                                        sender_id,
                                        'Not a valid project.'
                                    )
                            # return tasks up to a certain date
                            elif ' up to ' in message.lower():
                                date_string = message.lower().split(
                                    ' up to '
                                )[1]
                                datetime = None
                                try:
                                    datetime = parse(date_string)
                                except:
                                    send_FB_text(
                                        sender_id,
                                        (
                                            'Date text not recognized. \n'
                                            'Try using actual dates.'
                                        )
                                    )
                                if datetime:
                                    send_tasks(
                                        sender_id,
                                        tc.get_tasks_up_to_date(
                                            datetime.date()
                                        )
                                    )
                            # send a normal tasks response
                            else:
                                send_tasks(
                                    sender_id,
                                    tc.get_this_week_tasks()
                                )
                        # write a task due a certain date
                        elif ' due ' in message:
                            write_task(sender_id, tc, message)
                        else:
                            send_generic_response(sender_id)
                    # button handling
                    if 'postback' in event:
                        payload = event['postback']['payload']
                        print 'Payload: {0}'.format(payload)
                        if payload == 'tasks':
                            send_tasks(sender_id, tc.get_this_week_tasks())
                        elif payload == 'write':
                            send_write_request(sender_id)
                        elif 'task_id' in payload:
                            complete_task(
                                sender_id,
                                tc,
                                payload.split(':')[1]
                            )
                        elif 'remove_alert' in payload:
                            task_id = payload.split(':')[1]
                            job_id = [x for x in handle.bot_users.find(
                                {'user_id': tc.user_id}
                            )][0]['reminder_jobs'][task_id]
                            scheduler.remove_job(job_id)
                            remove_reminder_job(
                                tc.user_id,
                                task_id
                            )
                            send_FB_text(sender_id, 'Alert removed.')
        return Response()


def send_tasks(sender_id, tasks):
    for task in tasks:
        send_FB_buttons(
            sender_id,
            '* {0} (Due {1})'.format(
                task['content'],
                task['date_string'] if task['date_string'] else 'never'
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
        (
            'Enter your task as follows: '
            '<Task Name> due <Date string>. '
            'Enter \'never\' if there is no due date.'
        )
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


def complete_task(sender_id, tc, task_id):
    tc.complete_task(task_id)
    send_FB_text(sender_id, 'Task completed.')


def send_generic_response(sender_id):
    send_FB_buttons(
        sender_id,
        (
            'Hi there! Would you like view your tasks or write tasks?\n'
            'You can also view tasks by typing \'tasks\'.\n'
            'You can view tasks up to a certain date'
            ' by typing \'tasks up to <date_string>\'\n'
            'You can view tasks in a specific project'
            ' by typing \'tasks in <project_name>\'\n'
        ),
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


@app.route('/todoist_callback')
def todoist_callback(methods=['GET']):
    if request.method == 'GET':
        error = request.args.get('error', '')
        if error:
            return 'Error: ' + error
        state = request.args.get('state', '')
        code = request.args.get('code')
        access_token = get_token(code)
        print 'Access token: {0}'.format(access_token)
        handle.bot_users.update(
            {'access_token': 'temp'},
            {
                '$set': {
                    'access_token': access_token
                }
            }
        )
        return 'success' if access_token and \
            handle.bot_users.find(
                {'access_token': access_token}
            ).count() else 'failure'


def get_access_token(sender_id):
    handle.bot_users.insert(
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


@app.route('/todoist_notifications', methods=['POST'])
def todoist_notifications():
    if request.method == 'POST':
        data = json.loads(request.data)
        user_id = data['event_data']['user_id']
        bot_user = [x for x in handle.bot_users.find(
            {'user_id': user_id})][0]
        sender_id = bot_user['sender_id']
        access_token = bot_user['access_token']
        tc = TodoistClient(access_token)
        task = data['event_data']
        if data['event_name'] == 'item:added':
            if task['due_date_utc']:
                # tz naivete necessary to compare objects
                due_date = parse(task['due_date_utc']).replace(tzinfo=None)
                if due_date > (
                    datetime.now() + timedelta(minutes=REMINDER_OFFSET)
                ):  # only set alert if it is before the alert would happen
                    reminder_date = due_date - \
                        timedelta(minutes=REMINDER_OFFSET)
                    add_reminder_job(
                        reminder_date,
                        sender_id,
                        user_id,
                        task,
                        tc.tz_info['hours']
                    )
        elif data['event_name'] == 'item:completed' \
                or data['event_name'] == 'item:deleted':
            if 'reminder_jobs' in bot_user:
                reminder_jobs = bot_user['reminder_jobs']
                if str(task['id']) in reminder_jobs.keys():
                    remove_reminder_job(user_id, task['id'])
                    scheduler.remove_job(reminder_jobs[str(task['id'])])
        elif data['event_name'] == 'item:updated':
            print json.dumps(data['event_data'], indent=4)
        return Response()


def send_reminder(sender_id, user_id, task, mins_left):
    send_FB_buttons(
        sender_id,
        'Your task, "{0}", is due in {1} minutes!'.format(
            task['content'],
            mins_left
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
    remove_reminder_job(user_id, task['id'])


def remove_reminder_job(user_id, task_id):
    bot_user = [x for x in handle.bot_users.find(
        {'user_id': user_id})][0]
    reminder_jobs = bot_user['reminder_jobs']
    job_id = reminder_jobs.pop(str(task_id))
    handle.bot_users.update(
        {'user_id': user_id},
        {
            '$set': {
                'reminder_jobs': reminder_jobs
            }
        }
    )


def add_reminder_job(reminder_date, sender_id, user_id,
                     task, time_diff):
    job_id = uuid4().__str__()
    task_id = task['id']
    job = scheduler.add_job(
        send_reminder,
        args=[sender_id, user_id, task, REMINDER_OFFSET],
        trigger='cron',
        year=reminder_date.year,
        month=reminder_date.month,
        day=reminder_date.day,
        hour=reminder_date.hour,
        minute=reminder_date.minute,
        id=job_id
    )
    try:
        scheduler.start()
    except:
        print 'Scheduler running'
    bot_user = [x for x in handle.bot_users.find(
        {'user_id': user_id})][0]
    reminder_jobs = bot_user['reminder_jobs'] \
        if 'reminder_jobs' in bot_user else {}
    reminder_jobs[str(task_id)] = job_id
    handle.bot_users.update(
        {'user_id': user_id},
        {
            '$set': {
                'reminder_jobs': reminder_jobs
            }
        }
    )
    send_FB_buttons(
        sender_id,
        'An alert has been set for {0}.'.format(
            (
                (reminder_date + timedelta(hours=time_diff)).strftime(
                    '%A, %B %d at %-I:%M %p'
                )
            )
        ),
        [
            {
                'type': 'postback',
                'title': 'Remove alert',
                'payload': 'remove_alert:{0}'.format(
                    task['id']
                )
            }
        ]
    )


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


if __name__ == '__main__':
    scheduler.start()
    app.run(host='0.0.0.0', port=5000)
