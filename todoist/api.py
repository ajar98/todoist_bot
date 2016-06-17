import uuid
import json
import requests
import datetime
from functools import partial

from todoist import models
from todoist.managers.biz_invitations import BizInvitationsManager
from todoist.managers.filters import FiltersManager
from todoist.managers.invitations import InvitationsManager
from todoist.managers.live_notifications import LiveNotificationsManager
from todoist.managers.notes import NotesManager, ProjectNotesManager
from todoist.managers.projects import ProjectsManager
from todoist.managers.items import ItemsManager
from todoist.managers.labels import LabelsManager
from todoist.managers.reminders import RemindersManager
from todoist.managers.locations import LocationsManager
from todoist.managers.user import UserManager
from todoist.managers.collaborators import CollaboratorsManager
from todoist.managers.collaborator_states import CollaboratorStatesManager


class SyncError(Exception):
    pass


class TodoistAPI(object):
    """
    Implements the API that makes it possible to interact with a Todoist user
    account and its data.
    """
    _serialize_fields = ('token', 'api_endpoint', 'sync_token', 'state', 'temp_ids')


    @classmethod
    def deserialize(cls, data):
        obj = cls()
        for key in cls._serialize_fields:
            if key in data:
                setattr(obj, key, data[key])
        return obj

    def __init__(self, token='', api_endpoint='https://api.todoist.com', session=None):
        self.api_endpoint = api_endpoint
        self.reset_state()
        self.token = token  # User's API token
        self.temp_ids = {}  # Mapping of temporary ids to real ids
        self.queue = []  # Requests to be sent are appended here
        self.session = session or requests.Session()  # Session instance for requests

        # managers
        self.projects = ProjectsManager(self)
        self.project_notes = ProjectNotesManager(self)
        self.items = ItemsManager(self)
        self.labels = LabelsManager(self)
        self.filters = FiltersManager(self)
        self.notes = NotesManager(self)
        self.live_notifications = LiveNotificationsManager(self)
        self.reminders = RemindersManager(self)
        self.locations = LocationsManager(self)
        self.invitations = InvitationsManager(self)
        self.biz_invitations = BizInvitationsManager(self)
        self.user = UserManager(self)
        self.collaborators = CollaboratorsManager(self)
        self.collaborator_states = CollaboratorStatesManager(self)

    def reset_state(self):
        self.sync_token = '*'
        self.state = {  # Local copy of all of the user's objects
            'collaborator_states': [],
            'collaborators': [],
            'day_orders': {},
            'day_orders_timestamp': '',
            'filters': [],
            'items': [],
            'labels': [],
            'live_notifications': [],
            'live_notifications_last_read_id': -1,
            'locations': [],
            'notes': [],
            'project_notes': [],
            'projects': [],
            'reminders': [],
            'settings': {},
            'settings_notifications': {},
            'user': {},
            'web_static_version': -1,
        }

    def __getitem__(self, key):
        return self.state[key]

    def serialize(self):
        return {key: getattr(self, key) for key in self._serialize_fields}

    def get_api_url(self):
        return '%s/API/v7/' % self.api_endpoint

    def _update_state(self, syncdata):
        """
        Updates the local state, with the data returned by the server after a
        sync.
        """
        # Check sync token first
        self.sync_token = syncdata['sync_token']

        # It is straightforward to update these type of data, since it is
        # enough to just see if they are present in the sync data, and then
        # either replace the local values or update them.
        if 'collaborators' in syncdata:
            self.state['collaborators'] = syncdata['collaborators']
        if 'collaborator_states' in syncdata:
            self.state['collaborator_states'] = syncdata['collaborator_states']
        if 'day_orders' in syncdata:
            self.state['day_orders'].update(syncdata['day_orders'])
        if 'day_orders_timestamp' in syncdata:
            self.state['day_orders_timestamp'] = syncdata['day_orders_timestamp']
        if 'live_notifications_last_read_id' in syncdata:
            self.state['live_notifications_last_read_id'] = \
                syncdata['live_notifications_last_read_id']
        if 'locations' in syncdata:
            self.state['locations'] = syncdata['locations']
        if 'settings' in syncdata:
            self.state['settings'].update(syncdata['settings'])
        if 'settings_notifications' in syncdata:
            self.state['settings_notifications'].\
                update(syncdata['settings_notifications'])
        if 'user' in syncdata:
            self.state['user'].update(syncdata['user'])
        if 'web_static_version' in syncdata:
            self.state['web_static_version'] = syncdata['web_static_version']

        # Updating these type of data is a bit more complicated, since it is
        # necessary to find out whether an object in the sync data is new,
        # updates an existing object, or marks an object to be deleted.  But
        # the same procedure takes place for each of these types of data.
        resp_models_mapping = [
            ('filters', models.Filter),
            ('items', models.Item),
            ('labels', models.Label),
            ('live_notifications', models.LiveNotification),
            ('notes', models.Note),
            ('project_notes', models.ProjectNote),
            ('projects', models.Project),
            ('reminders', models.Reminder),
        ]
        for datatype, model in resp_models_mapping:
            if datatype not in syncdata:
                continue

            # Process each object of this specific type in the sync data.
            for remoteobj in syncdata[datatype]:
                # Find out whether the object already exists in the local
                # state.
                localobj = self._find_object(datatype, remoteobj)
                if localobj is not None:
                    # If the object is already present in the local state, then
                    # we either update it, or if marked as to be deleted, we
                    # remove it.
                    if remoteobj.get('is_deleted', 0) == 0:
                        localobj.data.update(remoteobj)
                    else:
                        self.state[datatype].remove(localobj)
                else:
                    # If not, then the object is new and it should be added,
                    # unless it is marked as to be deleted (in which case it's
                    # ignored).
                    if remoteobj.get('is_deleted', 0) == 0:
                        newobj = model(remoteobj, self)
                        self.state[datatype].append(newobj)

    def _find_object(self, objtype, obj):
        """
        Searches for an object in the local state, depending on the type of
        object, and then on its primary key is.  If the object is found it is
        returned, and if not, then None is returned.
        """
        if objtype == 'collaborators':
            return self.collaborators.get_by_id(obj['id'])
        elif objtype == 'collaborator_states':
            return self.collaborator_states.get_by_ids(obj['project_id'],
                                                       obj['user_id'])
        elif objtype == 'filters':
            return self.filters.get_by_id(obj['id'], only_local=True)
        elif objtype == 'items':
            return self.items.get_by_id(obj['id'], only_local=True)
        elif objtype == 'labels':
            return self.labels.get_by_id(obj['id'], only_local=True)
        elif objtype == 'live_notifications':
            return self.live_notifications.get_by_key(obj['notification_key'])
        elif objtype == 'notes':
            return self.notes.get_by_id(obj['id'], only_local=True)
        elif objtype == 'project_notes':
            return self.project_notes.get_by_id(obj['id'], only_local=True)
        elif objtype == 'projects':
            return self.projects.get_by_id(obj['id'], only_local=True)
        elif objtype == 'reminders':
            return self.reminders.get_by_id(obj['id'], only_local=True)
        else:
            return None

    def _replace_temp_id(self, temp_id, new_id):
        """
        Replaces the temporary id generated locally when an object was first
        created, with a real Id supplied by the server.  True is returned if
        the temporary id was found and replaced, and False otherwise.
        """
        # Go through all the objects for which we expect the temporary id to be
        # replaced by a real one.
        for datatype in ['filters', 'items', 'labels', 'notes', 'project_notes',
                         'projects', 'reminders']:
            for obj in self.state[datatype]:
                if obj.temp_id == temp_id:
                    obj['id'] = new_id
                    return True
        return False

    def _get(self, call, url=None, **kwargs):
        """
        Sends an HTTP GET request to the specified URL, and returns the JSON
        object received (if any), or whatever answer it got otherwise.
        """
        if not url:
            url = self.get_api_url()

        response = self.session.get(url + call, **kwargs)

        try:
            return response.json()
        except ValueError:
            return response.text

    def _post(self, call, url=None, **kwargs):
        """
        Sends an HTTP POST request to the specified URL, and returns the JSON
        object received (if any), or whatever answer it got otherwise.
        """
        if not url:
            url = self.get_api_url()

        response = self.session.post(url + call, **kwargs)

        try:
            return response.json()
        except ValueError:
            return response.text


    # Sync
    def generate_uuid(self):
        """
        Generates a uuid.
        """
        return str(uuid.uuid1())

    def sync(self, commands=None):
        """
        Sends to the server the changes that were made locally, and also
        fetches the latest updated data from the server.
        """
        post_data = {
            'token': self.token,
            'sync_token': self.sync_token,
            'day_orders_timestamp': self.state['day_orders_timestamp'],
            'include_notification_settings': 1,
            'resource_types': json_dumps(['all']),
            'commands': json_dumps(commands or []),
        }
        response = self._post('sync', data=post_data)
        if 'temp_id_mapping' in response:
            for temp_id, new_id in response['temp_id_mapping'].items():
                self.temp_ids[temp_id] = new_id
                self._replace_temp_id(temp_id, new_id)
        self._update_state(response)
        return response

    def commit(self, raise_on_error=True):
        """
        Commits all requests that are queued.  Note that, without calling this
        method none of the changes that are made to the objects are actually
        synchronized to the server, unless one of the aforementioned Sync API
        calls are called directly.
        """
        if len(self.queue) == 0:
            return
        ret = self.sync(commands=self.queue)
        del self.queue[:]
        if 'sync_status' in ret:
            if raise_on_error:
                for k, v in ret['sync_status'].items():
                    if v != 'ok':
                        raise SyncError(k, v)
        return ret

    # Authentication
    def login(self, email, password):
        """
        Logins user, and returns the response received by the server.
        """
        data = self._post('login', data={'email': email,
                                         'password': password})
        if 'token' in data:
            self.token = data['token']
        return data

    def login_with_google(self, email, oauth2_token, **kwargs):
        """
        Logins user with Google account, and returns the response received by
        the server.

        """
        data = {'email': email, 'oauth2_token': oauth2_token}
        data.update(kwargs)
        data = self._post('login_with_google', data=data)
        if 'token' in data:
            self.token = data['token']
        return data

    # User
    def register(self, email, full_name, password, **kwargs):
        """
        Registers a new user.
        """
        data = {'email': email, 'full_name': full_name, 'password': password}
        data.update(kwargs)
        data = self._post('register', data=data)
        if 'token' in data:
            self.token = data['token']
        return data

    def delete_user(self, current_password, **kwargs):
        """
        Deletes an existing user.
        """
        params = {'token': self.token,
                  'current_password': current_password}
        params.update(kwargs)
        return self._get('delete_user', params=params)

    # Miscellaneous
    def upload_file(self, filename, **kwargs):
        """
        Uploads a file.
        """
        data = {'token': self.token}
        data.update(kwargs)
        files = {'file': open(filename, 'rb')}
        return self._post('upload_file', self.get_api_url(), data=data,
                          files=files)

    def query(self, queries, **kwargs):
        """
        Performs date queries and other searches, and returns the results.
        """
        params = {'queries': json_dumps(queries),
                  'token': self.token}
        params.update(kwargs)
        return self._get('query', params=params)

    def get_redirect_link(self, **kwargs):
        """
        Returns the absolute URL to redirect or to open in a browser.
        """
        params = {'token': self.token}
        params.update(kwargs)
        return self._get('get_redirect_link', params=params)

    def get_productivity_stats(self):
        """
        Returns the user's recent productivity stats.
        """
        return self._get('get_productivity_stats',
                         params={'token': self.token})

    def update_notification_setting(self, notification_type, service,
                                    dont_notify):
        """
        Updates the user's notification settings.
        """
        return self._post('update_notification_setting',
                          data={'token': self.token,
                                'notification_type': notification_type,
                                'service': service,
                                'dont_notify': dont_notify})

    def get_all_completed_items(self, **kwargs):
        """
        Returns all user's completed items.
        """
        params = {'token': self.token}
        params.update(kwargs)
        return self._get('get_all_completed_items', params=params)

    def get_completed_items(self, project_id, **kwargs):
        """
        Returns a project's completed items.
        """
        params = {'token': self.token,
                  'project_id': project_id}
        params.update(kwargs)
        return self._get('get_completed_items', params=params)

    def get_uploads(self, **kwargs):
        """
        Returns all user's uploads.

        kwargs:
            limit: (int, optional) number of results (1-50)
            last_id: (int, optional) return results with id<last_id
        """
        params = {'token': self.token}
        params.update(kwargs)
        return self._get('uploads/get', params=params)

    def delete_upload(self, file_url):
        """
        Delete upload.

        param file_url: (str) uploaded file URL
        """
        params = {'token': self.token, 'file_url': file_url}
        return self._get('uploads/delete', params=params)

    def add_item(self, content, **kwargs):
        """
        Adds a new task.
        """
        params = {'token': self.token,
                  'content': content}
        params.update(kwargs)
        return self._get('add_item', params=params)

    # Sharing
    def share_project(self, project_id, email, message='', **kwargs):
        """
        Appends a request to the queue, to share a project with a user.
        """
        cmd = {
            'type': 'share_project',
            'temp_id': self.generate_uuid(),
            'uuid': self.generate_uuid(),
            'args': {
                'project_id': project_id,
                'email': email,
            },
        }
        cmd['args'].update(kwargs)
        self.queue.append(cmd)

    def delete_collaborator(self, project_id, email):
        """
        Appends a request to the queue, to delete a collaborator from a shared
        project.
        """
        cmd = {
            'type': 'delete_collaborator',
            'uuid': self.generate_uuid(),
            'args': {
                'project_id': project_id,
                'email': email,
            },
        }
        self.queue.append(cmd)

    def take_ownership(self, project_id):
        """
        Appends a request to the queue, take ownership of a shared project.
        """
        cmd = {
            'type': 'take_ownership',
            'uuid': self.generate_uuid(),
            'args': {
                'project_id': project_id,
            },
        }
        self.queue.append(cmd)

    # Auxiliary
    def get_project(self, project_id):
        """
        Gets an existing project.
        """
        params = {'token': self.token,
                  'project_id': project_id}
        obj = self._get('get_project', params=params)
        if obj and 'error' in obj:
            return None
        data = {'projects': [], 'project_notes': []}
        if obj.get('project'):
            data['projects'].append(obj.get('project'))
        if obj.get('notes'):
            data['project_notes'] += obj.get('notes')
        self._update_state(data)
        return obj

    def get_item(self, item_id):
        """
        Gets an existing item.
        """
        params = {'token': self.token,
                  'item_id': item_id}
        obj = self._get('get_item', params=params)
        if obj and 'error' in obj:
            return None
        data = {'projects': [], 'items': [], 'notes': []}
        if obj.get('project'):
            data['projects'].append(obj.get('project'))
        if obj.get('item'):
            data['items'].append(obj.get('item'))
        if obj.get('notes'):
            data['notes'] += obj.get('notes')
        self._update_state(data)
        return obj

    def get_label(self, label_id):
        """
        Gets an existing label.
        """
        params = {'token': self.token,
                  'label_id': label_id}
        obj = self._get('get_label', params=params)
        if obj and 'error' in obj:
            return None
        data = {'labels': []}
        if obj.get('label'):
            data['labels'].append(obj.get('label'))
        self._update_state(data)
        return obj

    def get_note(self, note_id):
        """
        Gets an existing note.
        """
        params = {'token': self.token,
                  'note_id': note_id}
        obj = self._get('get_note', params=params)
        if obj and 'error' in obj:
            return None
        data = {'notes': []}
        if obj.get('note'):
            data['notes'].append(obj.get('note'))
        self._update_state(data)
        return obj

    def get_filter(self, filter_id):
        """
        Gets an existing filter.
        """
        params = {'token': self.token,
                  'filter_id': filter_id}
        obj = self._get('get_filter', params=params)
        if obj and 'error' in obj:
            return None
        data = {'filters': []}
        if obj.get('filter'):
            data['filters'].append(obj.get('filter'))
        self._update_state(data)
        return obj

    def get_reminder(self, reminder_id):
        """
        Gets an existing reminder.
        """
        params = {'token': self.token,
                  'reminder_id': reminder_id}
        obj = self._get('get_reminder', params=params)
        if obj and 'error' in obj:
            return None
        data = {'reminders': []}
        if obj.get('reminder'):
            data['reminders'].append(obj.get('reminder'))
        self._update_state(data)
        return obj

    # Templates
    def import_template_into_project(self, project_id, filename, **kwargs):
        """
        Imports a template into a project.
        """
        data = {'token': self.token,
                'project_id': project_id}
        data.update(kwargs)
        files = {'file': open(filename, 'r')}
        return self._post('templates/import_into_project', self.get_api_url(),
                          data=data, files=files)

    def export_template_as_file(self, project_id, **kwargs):
        """
        Exports a template as a file.
        """
        data = {'token': self.token,
                'project_id': project_id}
        data.update(kwargs)
        return self._post('templates/export_as_file', self.get_api_url(),
                          data=data)

    def export_template_as_url(self, project_id, **kwargs):
        """
        Exports a template as a URL.
        """
        data = {'token': self.token,
                'project_id': project_id}
        data.update(kwargs)
        return self._post('templates/export_as_url', self.get_api_url(),
                          data=data)

    # Business
    def business_users_invite(self, email_list):
        """
        Send a business user invitation.
        """
        params = {'token': self.token,
                  'email_list': json.dumps(email_list)}
        return self._get('business/users/invite', params=params)

    def business_users_accept_invitation(self, id, secret):
        """
        Accept a business user invitation.
        """
        params = {'token': self.token,
                  'id': id,
                  'secret': secret}
        return self._get('business/users/accept_invitation', params=params)

    def business_users_reject_invitation(self, id, secret):
        """
        Reject a business user invitation.
        """
        params = {'token': self.token,
                  'id': id,
                  'secret': secret}
        return self._get('business/users/reject_invitation', params=params)

    # Class
    def __repr__(self):
        name = self.__class__.__name__
        unsaved = '*' if len(self.queue) > 0 else ''
        email = self.user.get('email')
        email_repr = repr(email) if email else '<not synchronized>'
        return '%s%s(%s)' % (name, unsaved, email_repr)


def json_default(obj):
    if isinstance(obj, datetime.datetime):
        return obj.strftime('%Y-%m-%dT%H:%M:%S')
    elif isinstance(obj, datetime.date):
        return obj.strftime('%Y-%m-%d')
    elif isinstance(obj, datetime.time):
        return obj.strftime('%H:%M:%S')


json_dumps = partial(json.dumps, separators=',:', default=json_default)
