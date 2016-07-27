from apscheduler.schedulers.blocking import BlockingScheduler
import os
from pymongo import MongoClient
from client import TodoistClient
from todoist_app import send_tasks, send_FB_text
from todoist_app import MONGO_DB_TOKENS_ENDPOINT, MONGO_DB_TOKENS_PORT
from todoist_app import MONGO_DB_TOKENS_DATABASE
from uuid import uuid4


DAY_OVERVIEW_TIME_HOUR = 6


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


scheduler = BlockingScheduler()
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
        print 'Clock for {0}'.format(entry['access_token'])
        tc = TodoistClient(entry['access_token'])
        job_id = uuid4().__str__()
        job = scheduler.add_job(
            today_tasks,
            args=[entry['sender_id'], tc],
            trigger='cron',
            hour=DAY_OVERVIEW_TIME_HOUR - tc.tz_info['hours'],
            id=job_id
        )
    scheduler.start()
