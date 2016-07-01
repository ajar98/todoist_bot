from apscheduler.schedulers.blocking import BlockingScheduler
import os
from pymongo import MongoClient
from client import TodoistClient
from todoist_app import send_tasks, send_FB_text
from datetime import datetime

MONGO_DB_ENDPOINT = 'ds021434.mlab.com'
MONGO_DB_PORT = 21434


def connect():
    connection = MongoClient(MONGO_DB_ENDPOINT, MONGO_DB_PORT)
    handle = connection['todoist_access_tokens']
    handle.authenticate(
    	os.environ['MONGO_DB_USERNAME'],
    	os.environ['MONGO_DB_PWD']
    )
    return handle


sched = BlockingScheduler()
handle = connect()


@sched.scheduled_job('cron', hour=13)
def today_tasks():
    for entry in handle.bot_users.find():
        if 'access_token' in entry:
        	tc = TodoistClient(entry['access_token'])
        	today_tasks = tc.get_today_tasks()
        	if today_tasks:
        		send_FB_text(
        			entry['sender_id'],
        			'Here are your tasks for today:'
        		)
        		send_tasks(
        			entry['sender_id'],
        			today_tasks
        		)
        	else:
				send_FB_text(
					entry['sender_id'],
					'You have no tasks today! Have a great day!'
				)
            # send_FB_text(
            #     entry['sender_id'],
            #     (
            #         'To set when your tasks for the day are sent to you, '
            #         'type "set day overview time to <date_string>"'
            #     )
            # )


sched.start()
