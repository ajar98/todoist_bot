import json
from todoist.api import TodoistAPI
import random
import string

# implement labels
# create a new project
# create a task in a new project


TOKEN = 'e5d57a2cbb3a10c236c78eba3d578e18f875a4ee'
INBOX_PROJECT_ID = 147001862

ID_LENGTH = 20

ADD_TASK_TYPE = 'item_add'


class TodoistClient():

    def __init__(self, token):
        self.token = token
        self.sync_response = self.api.sync(resource_types=['all'])

    @property
    def api(self):
        return TodoistAPI(self.token)

    def get_project_to_id(self, project_name):
        if project_name == 'Inbox':
            return self.sync_response['User']['inbox_project']
        else: 
            for project in self.sync_response['Projects']:
                if project_name == project['name']:
                    return project['id']
        return None

    def write(self, commands):
        return self.api.sync(commands=commands)

    def write_task(self, task_name, project_name, date_string=None, priority=1):
        return self.write([
            WriteTask(
                task_name,
                self.get_project_to_id(project_name),
                date_string,
                priority
                ).to_dict()
            ])

    def write_inbox_task(self, task_name):
        return self.write_task(task_name, "Inbox")


class Command(object):

    def __init__(self, command_type, args):
        self.type = command_type
        self.args = args
        self.uuid = self.generate_id()
        self.temp_id = self.generate_id()

    def generate_id(self):
        return ''.join(random.choice(string.ascii_lowercase) for i in range(ID_LENGTH))

    def to_dict(self):
        return {
            'type': self.type,
            'args': self.args,
            'uuid': self.uuid,
            'temp_id': self.temp_id
        }


class WriteTask(Command):

    def __init__(self, task_name, project_id, date_string=None, priority=1, label_ids=[]):
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


# class CreateProject(Command):




if __name__ == '__main__':
    tc = TodoistClient(TOKEN)
    print tc.write_task('Madhavi Computer Class Meeting', 'Inbox', date_string='Wednesday 4:30pm')



