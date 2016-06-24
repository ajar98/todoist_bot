from apscheduler.schedulers.blocking import BlockingScheduler
from pymongo import MongoClient
from client import TodoistClient
from todoist_app import send_tasks

MONGO_DB_ENDPOINT = 'ds021434.mlab.com'

def connect():
    connection = MongoClient(MONGO_DB_ENDPOINT, 21434)
    handle = connection['todoist_access_tokens']
    handle.authenticate('chatbot', 'weaboo')
    return handle

sched = BlockingScheduler()
handle = connect()


@sched.scheduled_job('interval', minutes=1)
def timed_job():
	for entry in handle.access_tokens.find():
		tc = TodoistClient(entry['access_token'])
		send_tasks(entry['sender_id'], tc.get_today_tasks())


# @sched.scheduled_job('cron', day_of_week='mon-fri', hour=17)
# def scheduled_job():
#     print 'This job is run every weekday at 5pm.'


sched.start()
