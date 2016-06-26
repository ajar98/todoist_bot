from apscheduler.schedulers.blocking import BlockingScheduler
from pymongo import MongoClient
from client import TodoistClient
from todoist_app import send_tasks, send_FB_text

MONGO_DB_ENDPOINT = 'ds021434.mlab.com'


def connect():
    connection = MongoClient(MONGO_DB_ENDPOINT, 21434)
    handle = connection['todoist_access_tokens']
    handle.authenticate('chatbot', 'weaboo')
    return handle

sched = BlockingScheduler()
handle = connect()


@sched.scheduled_job('cron', hour=6)
def today_tasks():
    for entry in handle.access_tokens.find():
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


sched.start()
