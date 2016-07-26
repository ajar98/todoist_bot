from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.mongodb import MongoDBJobStore
import os
from pymongo import MongoClient
from client import TodoistClient
from todoist_app import send_tasks, send_FB_text
from todoist_app import MONGO_DB_TOKENS_ENDPOINT, MONGO_DB_TOKENS_PORT
from todoist_app import MONGO_DB_TOKENS_DATABASE
from todoist_app import MONGO_DB_JOBS_URL
from dateutil.parser import parse
from datetime import timedelta
from uuid import uuid4


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


scheduler = BackgroundScheduler(jobstores={
    'default': MongoDBJobStore(host=MONGO_DB_JOBS_URL)
})
handle = connect()


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


if __name__ == '__main__':
    for entry in handle.bot_users.find():
        tc = TodoistClient(entry['access_token'])
        job_id = uuid4().__str__()
        agenda_time = parse('6 AM') - timedelta(hours=tc.tz_info['hours'])
        job = scheduler.add_job(
            today_tasks,
            args=[entry['sender_id'], tc],
            trigger='cron',
            hour=agenda_time.hour,
            minute=agenda_time.minute,
            id=job_id
        )
    scheduler.start()
