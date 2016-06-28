import json
from todoist.api import TodoistAPI
import random
import string
from dateutil.parser import parse
import datetime
from datetime import timedelta
from uuid import uuid4

# implement labels
# create a new project
# create a task in a new project

ID_LENGTH = 20

ADD_TASK_TYPE = 'item_add'
ITEM_COMPLETE_TYPE = 'item_complete'


class TodoistClient():

    def __init__(self, token):
        self.token = token
        self.sync_response = self.api.sync()

    @property
    def api(self):
        return TodoistAPI(self.token)

    def get_project_to_id(self, project_name):
        for project in self.sync_response['projects']:
            if project_name.lower() == project['name'].lower():
                return project['id']
        return None

    def write(self, commands):
        return self.api.sync(commands=commands)

    def write_task(self, task_name, project_name,
                   date_string=None, priority=1):
        return self.write(
            [
                WriteTask(
                    task_name,
                    self.get_project_to_id(project_name),
                    date_string,
                    priority
                ).to_dict()
            ]
        )

    def write_inbox_task(self, task_name):
        return self.write_task(task_name, "Inbox")

    def complete_task(self, task_id):
        return self.write(
            [
                CompleteTask(
                    task_id
                ).to_dict()
            ]
        )

    def get_today_tasks(self):
        return self.get_tasks_up_to_date(datetime.date.today())

    def get_project_tasks(self, project_name):
        project_id = self.get_project_to_id(project_name)
        return [
            task for task in self.sync_response['items']
            if task['project_id'] == project_id
        ] if project_id else None

    def get_this_week_tasks(self):
        return self.get_tasks_up_to_date(
            datetime.date.today() + timedelta(weeks=1))

    def get_tasks_up_to_date(self, date, sort_by_priority=False):
        return self.sort_tasks_by_date([
            task for task in self.sync_response['items']
            if task['due_date_utc']
            and parse(task['due_date_utc']).date() <= date
        ])

    def sort_tasks_by_date(self, tasks):
        return sorted(tasks, key=lambda t: parse(t['due_date_utc']).date())

    def sort_tasks_by_priority(self, tasks):
        return sorted(tasks, key=lambda t: t['priority'])


class Command(object):

    def __init__(self, command_type, args):
        self.type = command_type
        self.args = args
        self.uuid = uuid4().__str__()
        self.temp_id = self.generate_id()

    def to_dict(self):
        return {
            'type': self.type,
            'args': self.args,
            'uuid': self.uuid,
            'temp_id': self.temp_id
        }


class WriteTask(Command):

    def __init__(self, task_name, project_id,
                 date_string=None, priority=1, label_ids=[]):
        super(WriteTask, self).__init__(
            ADD_TASK_TYPE,
            {
                'content': task_name,
                'project_id': project_id,
                'date_string': date_string,
                'priority': priority,
                'labels': label_ids
            }
        )


class CompleteTask(Command):

    def __init__(self, task_id):
        super(CompleteTask, self).__init__(
            ITEM_COMPLETE_TYPE,
            {
                'ids': [task_id]
            }
        )
