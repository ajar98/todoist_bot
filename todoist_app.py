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
from apscheduler.schedulers import SchedulerAlreadyRunningError
from apscheduler.jobstores.mongodb import MongoDBJobStore

FB_ENDPOINT = 'https://graph.facebook.com/v2.6/me/{0}'
FB_MESSAGES_ENDPOINT = FB_ENDPOINT.format('messages')
FB_THREAD_SETTINGS_ENDPOINT = FB_ENDPOINT.format('thread_settings')
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
        send_persistent_menu()
        data = json.loads(request.data)['entry'][0]['messaging']
        for i in range(len(data)):
            event = data[i]
            # check if the event was sent by someone
            if 'sender' in event:
                sender_id = event['sender']['id']
                # get Todoist access token if there is none in MongoDB
                if handle.bot_users.find(
                    {'sender_id': sender_id}
                ).count() == 0:
                    send_FB_text(
                        sender_id,
                        (
                            'Welcome to TodoistBot! Here you can '
                            'write and view your tasks from Todoist.'
                        )
                    )
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
                        app.logger.info('Message: {0}'.format(message))
                        if 'quick_reply' in event['message']:
                            payload = \
                                event['message']['quick_reply']['payload']
                            if payload == 'tasks':
                                send_tasks(
                                    sender_id,
                                    tc.get_this_week_tasks(),
                                    tc.tz_info['hours']
                                )
                            elif payload == 'write':
                                send_write_request(sender_id)
                        elif 'tasks' in message.lower():
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
                                            project_tasks,
                                            tc.tz_info['hours']
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
                                        ),
                                        tc.tz_info['hours']
                                    )
                            # send a normal tasks response
                            else:
                                send_tasks(
                                    sender_id,
                                    tc.get_this_week_tasks(),
                                    tc.tz_info['hours']
                                )
                        # write a task due a certain date
                        elif ' due ' in message:
                            write_task(sender_id, tc, message)
                        elif 'alert offset' in message:
                            try:
                                new_offset = int(message.replace(
                                    'set alert offset to ', ''
                                ).split(' ')[0])
                            except ValueError:
                                send_FB_text(sender_id, 'Invalid input.')
                            else:
                                handle.bot_users.update(
                                    {'user_id': tc.user_id},
                                    {
                                        '$set': {
                                            'reminder_offset': new_offset
                                        }
                                    }
                                )
                                send_FB_text(
                                    sender_id,
                                    'Alert settings changed.'
                                )
                        elif 'set day overview time to ' in message:
                            date_string = message.replace(
                                'set day overview time to ',
                                ''
                            )
                            try:
                                new_agenda_time = \
                                    parse(date_string) - \
                                    timedelta(hours=tc.tz_info['hours'])
                            except ValueError:
                                send_FB_text(
                                    sender_id,
                                    'Invalid date string. Try again'
                                )
                            else:
                                bot_user = [x for x in handle.bot_users.find(
                                    {'access_token': access_token})][0]
                                agenda_time_id = bot_user['agenda_time_id'] \
                                    if 'agenda_time_id' in bot_user else None
                                if agenda_time_id:
                                    scheduler.remove_job(agenda_time_id)
                                    agenda_job = scheduler.add_job(
                                        today_tasks,
                                        args=[sender_id, tc],
                                        trigger='cron',
                                        hour=new_agenda_time.hour,
                                        minute=new_agenda_time.minute,
                                        id=agenda_time_id
                                    )
                                    send_FB_text(
                                        sender_id,
                                        'Day overview time updated.'
                                    )
                                else:
                                    send_FB_text(
                                        sender_id,
                                        'No day overview scheduled.'
                                    )
                        else:
                            send_generic_response(sender_id)
                    # button handling
                    if 'postback' in event:
                        payload = event['postback']['payload']
                        app.logger.info('Payload: {0}'.format(payload))
                        if payload == 'tasks':
                            send_tasks(
                                sender_id,
                                tc.get_this_week_tasks(),
                                tc.tz_info['hours']
                            )
                        elif payload == 'write':
                            send_write_request(sender_id)
                        elif 'complete' in payload:
                            complete_task(
                                sender_id,
                                tc,
                                payload.split(':')[1]
                            )
                        elif 'postpone' in payload:
                            postpone_tomorrow_task(
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


def send_tasks(sender_id, tasks, time_diff):
    for task in tasks:
        buttons = [
            {
                'type': 'postback',
                'title': 'Complete',
                'payload': 'complete {0}:{1}'.format(
                    'task_id',
                    task['id']
                )
            }
        ]
        if task['due_date_utc'] + timedelta(hours=time_diff) \
                < (datetime.now() + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0):
            buttons += {
                'type': 'postback',
                'title': 'Postpone to tomorrow',
                'payload': 'postpone {0}:{1}'.format(
                    'task_id',
                    task['id']
                )
            }
        send_FB_buttons(
            sender_id,
            '{0} (Due {1})'.format(
                task['content'],
                task['date_string'] if task['date_string'] else 'never'
            ),
            buttons
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


def postpone_task(sender_id, tc, task_id, new_date_string):
    tc.update_task(task_id, date_string=new_date_string)
    send_FB_text(sender_id, 'Task postponed.')


def postpone_tomorrow_task(sender_id, tc, task_id):
    postpone_task(sender_id, tc, task_id, 'tomorrow')


def send_generic_response(sender_id):
    send_FB_text(
        sender_id,
        (
            'Hi there! Would you like view your tasks or write tasks?\n'
            'You can also view tasks by typing \'tasks\'.\n'
            'You can view tasks up to a certain date'
            ' by typing \'tasks up to <date_string>\'\n'
            'You can view tasks in a specific project'
            ' by typing \'tasks in <project_name>\'\n'
        ),
        quick_replies=[
            {
                'content_type': 'text',
                'title': 'View my tasks',
                'payload': 'tasks'
            },
            {
                'content_type': 'text',
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
        app.logger.info('Access token: {0}'.format(access_token))
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
        'But first, it looks like you haven\'t authorized Todoist.',
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
        if not('reminder_offset' in bot_user):
            handle.bot_users.update(
                {'user_id': user_id},
                {
                    '$set': {
                        'reminder_offset': 30
                    }
                }
            )
        sender_id = bot_user['sender_id']
        access_token = bot_user['access_token']
        tc = TodoistClient(access_token)
        task = data['event_data']
        if data['event_name'] == 'item:added':
            if task['due_date_utc']:
                # tz naivete necessary to compare objects
                due_date = parse(task['due_date_utc']).replace(tzinfo=None)
                if due_date > (
                    datetime.now() + timedelta(
                        minutes=bot_user['reminder_offset'])
                ):  # only set alert if it is before the alert would happen
                    reminder_date = due_date - \
                        timedelta(minutes=bot_user['reminder_offset'])
                    add_reminder_job(
                        reminder_date,
                        sender_id,
                        user_id,
                        task,
                        bot_user['reminder_offset'],
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
            reminder_jobs = bot_user['reminder_jobs']
            if str(task['id']) in reminder_jobs.keys():
                remove_reminder_job(user_id, task['id'])
                scheduler.remove_job(reminder_jobs[str(task['id'])])
            if task['due_date_utc']:
                # tz naivete necessary to compare objects
                due_date = parse(task['due_date_utc']).replace(tzinfo=None)
                if due_date > (
                    datetime.now() + timedelta(
                        minutes=bot_user['reminder_offset'])
                ):  # only set alert if it is before the alert would happen
                    reminder_date = due_date - \
                        timedelta(minutes=bot_user['reminder_offset'])
                    add_reminder_job(
                        reminder_date,
                        sender_id,
                        user_id,
                        task,
                        bot_user['reminder_offset'],
                        tc.tz_info['hours']
                    )
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
                     task, reminder_offset, time_diff):
    job_id = uuid4().__str__()
    task_id = task['id']
    job = scheduler.add_job(
        send_reminder,
        args=[sender_id, user_id, task, reminder_offset],
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
    except SchedulerAlreadyRunningError:
        app.logger.info('Scheduler running')
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
        'An alert has been set for task {0} at {1}.'.format(
            task['content'],
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
    send_FB_text(
        sender_id,
        (
            'You can change the amount of time between the alert'
            ' and the due date by typing "set alert offset to <x> minutes"'
        )
    )


def today_tasks(sender_id, tc):
    today_tasks = tc.get_today_tasks()
    if today_tasks:
        send_FB_text(
            sender_id,
            'Here are your tasks for today:'
        )
        send_tasks(
            sender_id,
            today_tasks,
            tc.tz_info['hours']
        )
    else:
        send_FB_text(
            sender_id,
            'You have no tasks today! Have a great day!'
        )
    send_FB_text(
        sender_id,
        (
            'To set when your tasks for the day are sent to you, '
            'type "set day overview time to <date_string>"'
        )
    )


def send_persistent_menu():
    fb_response = requests.post(
        FB_THREAD_SETTINGS_ENDPOINT,
        params={'access_token': os.environ['FB_APP_TOKEN']},
        data=json.dumps(
            {
                'setting_type': 'call_to_actions',
                'thread_state': 'existing_thread',
                'call_to_actions': [
                    {
                        'type': 'postback',
                        'title': 'View tasks',
                        'payload': 'tasks'
                    },
                    {
                        'type': 'postback',
                        'title': 'Write tasks',
                        'payload': 'write'
                    }
                ]
            }
        ),
        headers={'content-type': 'application/json'}
    )
    if not fb_response.ok:
        app.logger.warning('Not OK: {0}: {1}'.format(
            fb_response.status_code,
            fb_response.text
        ))
    else:
        app.logger.info('OK: {0}'.format(200))


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
        headers={'content-type': 'application/json'}
    )
    if not fb_response.ok:
        app.logger.warning('Not OK: {0}: {1}'.format(
            fb_response.status_code,
            fb_response.text
        ))
    else:
        app.logger.info('OK: {0}'.format(200))


def send_FB_text(sender_id, text, quick_replies=[]):
    return send_FB_message(
        sender_id,
        {
            'text': text,
            'quick_replies': quick_replies
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
