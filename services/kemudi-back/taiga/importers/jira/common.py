# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2021-present Kaleidos INC

import datetime
import os
import re
import requests
import unicodedata
from urllib.parse import parse_qsl, quote_plus
from oauthlib.oauth1 import SIGNATURE_RSA

from requests_oauthlib import OAuth1
from django.core.files.base import ContentFile
from django.template.defaultfilters import slugify
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.conf import settings

from taiga.users.models import User
from taiga.projects.models import Membership, Points, Project
from taiga.projects.userstories.models import UserStory
from taiga.projects.tasks.models import Task
from taiga.projects.issues.models import Issue
from taiga.projects.milestones.models import Milestone
from taiga.projects.epics.models import Epic
from taiga.projects.attachments.models import Attachment
from taiga.projects.history.services import take_snapshot
from taiga.projects.history.services import (make_diff_from_dicts,
                                             make_diff_values,
                                             make_key_from_model_object,
                                             get_typename_for_model_class,
                                             FrozenDiff)
from taiga.projects.custom_attributes.models import (UserStoryCustomAttribute,
                                                     TaskCustomAttribute,
                                                     IssueCustomAttribute,
                                                     EpicCustomAttribute)
from taiga.projects.history.models import HistoryEntry
from taiga.projects.history.choices import HistoryType
from taiga.mdrender.service import render as mdrender
from taiga.importers import exceptions
from taiga.front.templatetags.functions import resolve as resolve_front_url

def jira_user_id(user):
    """Stable identifier for a Jira user across Jira Cloud and Server.

    Jira Cloud removed ``key``/``name`` from the user API (GDPR) and uses
    ``accountId`` instead. Older Jira Server returned ``key``/``name``. This
    returns whichever is available so user bindings line up regardless of the
    Jira flavour. Accepts a user dict or ``None``."""
    if not user:
        return None
    return user.get('accountId') or user.get('key') or user.get('name')


def _norm_name(text):
    """Fold a display name / username / e-mail local part down to comparable
    lowercase words: strips accents and every non-alphanumeric character."""
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'[^a-z0-9]+', ' ', text.lower())
    return re.sub(r'\s+', ' ', text).strip()


def _positional_prefix(a, b):
    """True when two normalised names line up token by token, allowing either
    side to be abbreviated: "eka m sutisna" ~ "eka meiman sutisna",
    "l sendy dwi a" ~ "leonardo sendy dwi atmoko". At least one token has to
    match in full so that "a b" does not match everything."""
    ta, tb = a.split(), b.split()
    if not ta or len(ta) != len(tb):
        return False
    exact = 0
    for x, y in zip(ta, tb):
        if x == y:
            if len(x) >= 3:
                exact += 1
            continue
        if not (x.startswith(y) or y.startswith(x)):
            return False
    return exact >= 1


def _contained(a, b, minlen=6):
    """One name is the other with a suffix, ignoring spaces:
    "ferdinandharyanto" ~ "ferdinandharyanto39"."""
    a, b = a.replace(' ', ''), b.replace(' ', '')
    if len(a) < minlen or len(b) < minlen:
        return False
    return a.startswith(b) or b.startswith(a)


EPIC_COLORS = {
    "ghx-label-0": "#ffffff",
    "ghx-label-1": "#815b3a",
    "ghx-label-2": "#f79232",
    "ghx-label-3": "#d39c3f",
    "ghx-label-4": "#3b7fc4",
    "ghx-label-5": "#4a6785",
    "ghx-label-6": "#8eb021",
    "ghx-label-7": "#ac707a",
    "ghx-label-8": "#654982",
    "ghx-label-9": "#f15c75",
}


def links_to_richtext(importer, issue, links):
    richtext = ""
    importing_project_key = issue['key'].split("-")[0]
    for link in links:
        if "inwardIssue" in link:
            (project_key, issue_key) = link['inwardIssue']['key'].split("-")
            action = link['type']['inward']
        elif "outwardIssue" in link:
            (project_key, issue_key) = link['outwardIssue']['key'].split("-")
            action = link['type']['outward']
        else:
            continue

        if importing_project_key == project_key:
            richtext += "  * This item {} #{}\n".format(action, issue_key)
        else:
            url = importer._client.server + "/projects/{}/issues/{}-{}".format(
                project_key,
                project_key,
                issue_key
            )
            richtext += "  * This item {} [{}-{}]({})\n".format(action, project_key, issue_key, url)

    for link in links:
        if "object" in link:
            richtext += "  * [{}]({})\n".format(
                link['object']['title'] or link['object']['url'],
                link['object']['url'],
            )

    return richtext


class JiraClient:
    def __init__(self, server, oauth):
        self.server = server
        self.api_url = server + "/rest/agile/1.0/{}"
        self.main_api_url = server + "/rest/api/2/{}"
        if oauth:
            self.oauth = OAuth1(
                oauth['consumer_key'],
                signature_method=SIGNATURE_RSA,
                rsa_key=oauth['key_cert'],
                resource_owner_key=oauth['access_token'],
                resource_owner_secret=oauth['access_token_secret']
            )
        else:
            self.oauth = None

    def get(self, uri_path, query_params=None):
        headers = {
            'Content-Type': "application/json"
        }
        if query_params is None:
            query_params = {}

        if uri_path[0] == '/':
            uri_path = uri_path[1:]

        # Jira Cloud removed GET /rest/api/2/search (HTTP 410, CHANGE-2046) in
        # favour of the cursor-paginated /rest/api/3/search/jql. Transparently
        # translate the legacy call so every caller keeps working unchanged:
        # follow nextPageToken to gather all matching issues and return them in
        # the old {issues, startAt, maxResults, total} envelope. maxResults is
        # reported one above the result count so the callers' classic
        # "len(issues) < maxResults -> stop" loops complete in a single pass.
        if uri_path == 'search':
            return self._search_jql(query_params)

        url = self.main_api_url.format(uri_path)

        response = requests.get(url, params=query_params, headers=headers, auth=self.oauth)

        if response.status_code == 401:
            raise Exception("Unauthorized: %s at %s" % (response.text, url), response)
        if response.status_code != 200:
            raise Exception("Resource Unavailable: %s at %s" % (response.text, url), response)

        return response.json()

    def _search_jql(self, query_params):
        search_url = self.server + "/rest/api/3/search/jql"
        headers = {'Content-Type': "application/json"}
        base_params = {
            "jql": query_params.get("jql", ""),
            "maxResults": 100,
        }
        # Pass through the field/expand selectors the importer relies on
        # (fields=*all, expand=changelog). The new endpoint ignores the unknown
        # "attachment" expand token, and attachments still arrive via fields.
        # The legacy /search returned navigable fields by default, but
        # /search/jql returns only the issue id unless fields are requested --
        # so default to *all to keep issue['fields'] populated for callers that
        # omit it (e.g. _link_epics_with_user_stories).
        base_params["fields"] = query_params.get("fields") or "*all"
        if query_params.get("expand") is not None:
            base_params["expand"] = query_params["expand"]

        all_issues = []
        next_token = None
        while True:
            page_params = dict(base_params)
            if next_token:
                page_params["nextPageToken"] = next_token
            response = requests.get(search_url, params=page_params, headers=headers, auth=self.oauth)
            if response.status_code == 401:
                raise Exception("Unauthorized: %s at %s" % (response.text, search_url), response)
            if response.status_code != 200:
                raise Exception("Resource Unavailable: %s at %s" % (response.text, search_url), response)
            data = response.json()
            all_issues.extend(data.get("issues", []))
            if data.get("isLast", True) or not data.get("nextPageToken"):
                break
            next_token = data["nextPageToken"]

        return {
            "issues": all_issues,
            "startAt": 0,
            "maxResults": len(all_issues) + 1,
            "total": len(all_issues),
        }

    def get_agile(self, uri_path, query_params=None):
        headers = {
            'Content-Type': "application/json"
        }
        if query_params is None:
            query_params = {}

        if uri_path[0] == '/':
            uri_path = uri_path[1:]
        url = self.api_url.format(uri_path)

        response = requests.get(url, params=query_params, headers=headers, auth=self.oauth)

        if response.status_code == 401:
            raise Exception("Unauthorized: %s at %s" % (response.text, url), response)
        if response.status_code != 200:
            raise Exception("Resource Unavailable: %s at %s" % (response.text, url), response)

        return response.json()

    def raw_get(self, absolute_uri, query_params=None):
        if query_params is None:
            query_params = {}

        response = requests.get(absolute_uri, params=query_params, auth=self.oauth)

        if response.status_code == 401:
            raise Exception("Unauthorized: %s at %s" % (response.text, absolute_uri), response)
        if response.status_code != 200:
            raise Exception("Resource Unavailable: %s at %s" % (response.text, absolute_uri), response)

        return response.content

    def get_issue_url(self, key):
        (project_key, issue_key) = key.split("-")
        return self.server + "/projects/{}/issues/{}".format(project_key, key)


class JiraImporterCommon:
    def __init__(self, user, server, oauth):
        self._user = user
        self._client = JiraClient(server=server, oauth=oauth)

    # ------------------------------------------------------------------
    # Jira user -> Taiga user
    #
    # The wizard's `users_bindings` map is filled in by hand and is very often
    # left empty, in which case every `users_bindings.get(...)` misses and the
    # whole import lands unassigned (and the changelog gets the -1/-2 sentinels
    # instead of real people). So fall back to matching the Jira user against
    # the existing Taiga accounts. Set JIRA_IMPORT_MATCH_USERS=0 to turn the
    # fallback off and keep the plain wizard-only behaviour.
    # ------------------------------------------------------------------
    AUTOMATCH_USERS = os.getenv('JIRA_IMPORT_MATCH_USERS', '1') == '1'

    def _taiga_user_candidates(self):
        cache = getattr(self, '_taiga_user_cache', None)
        if cache is None:
            cache = []
            for user in User.objects.filter(is_active=True):
                email = (user.email or '').lower()
                cache.append((
                    user,
                    _norm_name(user.full_name),
                    _norm_name(user.username),
                    _norm_name(email.split('@')[0]),
                    email,
                ))
            self._taiga_user_cache = cache
        return cache

    def _match_taiga_user(self, jira_user):
        """Best-effort match of a Jira user onto an existing Taiga account.

        Only confident tiers are used -- exact e-mail, exact full name,
        username / e-mail local part, token-prefix, containment. An import must
        never silently hand somebody else's work over, so a tie inside the best
        tier (or no hit at all) returns None and the item stays unassigned."""
        if not self.AUTOMATCH_USERS or not jira_user:
            return None
        email = (jira_user.get('emailAddress') or '').strip().lower()
        name = _norm_name(jira_user.get('displayName') or jira_user.get('name') or '')
        if not email and not name:
            return None

        buckets = {}
        for user, nfull, nuser, nmail, umail in self._taiga_user_candidates():
            tier = None
            if email and umail and email == umail:
                tier = 0
            elif name and nfull and name == nfull:
                tier = 1
            elif name and ((nuser and name == nuser) or (nmail and name == nmail)):
                tier = 2
            elif name and any(c and _positional_prefix(name, c)
                              for c in (nfull, nuser, nmail)):
                tier = 3
            elif name and any(c and _contained(name, c) for c in (nfull, nmail)):
                tier = 4
            if tier is not None:
                buckets.setdefault(tier, []).append(user)

        if not buckets:
            return None
        best = buckets[min(buckets)]
        return best[0] if len(best) == 1 else None

    def _resolve_user(self, jira_user, users_bindings, default=None):
        """What the wizard mapped wins; otherwise auto-match. The result is
        written back into users_bindings so one lookup serves every issue and
        the answer stays consistent across items."""
        jira_id = jira_user_id(jira_user)
        if jira_id is not None and users_bindings.get(jira_id) is not None:
            return users_bindings[jira_id]
        matched = self._match_taiga_user(jira_user)
        if matched is None:
            return default
        if jira_id is not None:
            users_bindings[jira_id] = matched
        return matched

    def _resolve_user_ref(self, jira_id, display_name, users_bindings, default=None):
        """Same as _resolve_user for changelog rows, which carry only the Jira
        user id and the display name rather than a full user object."""
        if jira_id is not None and users_bindings.get(jira_id) is not None:
            return users_bindings[jira_id]
        matched = self._match_taiga_user({'displayName': display_name})
        if matched is None:
            return default
        if jira_id is not None:
            users_bindings[jira_id] = matched
        return matched

    def _ensure_assignee_memberships(self, project):
        """Everybody who ended up assigned to something has to be a project
        member, otherwise the assignee filters in the UI do not list them.
        bulk_create skips signals, so nobody gets an invitation e-mail."""
        assigned = set()
        for model in (UserStory, Task, Issue, Epic):
            assigned.update(
                model.objects.filter(project=project, assigned_to__isnull=False)
                     .values_list('assigned_to_id', flat=True))
        assigned.discard(None)
        missing = assigned - set(project.memberships.values_list('user_id', flat=True))
        if not missing:
            return
        role = project.roles.filter(computable=True).first() or project.roles.first()
        if role is None:
            return
        try:
            Membership.objects.bulk_create([
                Membership(project=project, user_id=user_id, role=role,
                           is_admin=False, email=email)
                for user_id, email in User.objects.filter(id__in=missing)
                                          .values_list('id', 'email')
            ])
        except Exception:
            # a missing membership only degrades the filters; never abort an
            # otherwise finished import over it
            pass

    def resolve_user_bindings(self, options):
        def resolve_user(user_id):
            if isinstance(user_id, User):
                return user_id
            try:
                user = User.objects.get(id=user_id)
                return user
            except User.DoesNotExist:
                return None

        options['users_bindings'] = {k: resolve_user(v) for k,v in options['users_bindings'].items() if v is not None}

    def list_users(self, project_id=None):
        # Jira Cloud's /user/assignable/multiProjectSearch only ever returns the
        # requesting user, so query the per-project assignable list instead,
        # which correctly returns every member of the project. The "project"
        # param accepts both the numeric project id (what the wizard sends) and
        # the project key. Falls back to the union across all visible projects
        # when no project is given. Jira Cloud identifies users by accountId;
        # older Jira Server used key/name -- jira_user_id() handles both.
        if project_id:
            project_refs = [project_id]
        else:
            project_refs = [p['key'] for p in self._client.get('/project')]

        result = []
        seen = set()
        for ref in project_refs:
            start_at = 0
            while True:
                users = self._client.get("/user/assignable/search", {
                    "project": ref,
                    "query": "",
                    "startAt": start_at,
                    "maxResults": 1000,
                })
                if not users:
                    break
                for user in users:
                    # Skip Connect/Forge apps and JSM customer accounts; keep
                    # regular users. Jira Server users have no accountType, so
                    # default to including them.
                    if user.get('accountType', 'atlassian') != 'atlassian':
                        continue
                    user_id = jira_user_id(user)
                    if not user_id or user_id in seen:
                        continue
                    seen.add(user_id)
                    result.append({
                        "id": user_id,
                        "full_name": user.get('displayName'),
                        "email": user.get('emailAddress', '') or '',
                        "avatar": user.get('avatarUrls', None) and user['avatarUrls'].get('48x48', None),
                    })
                if len(users) < 1000:
                    break
                start_at += len(users)
        return result

    def _import_comments(self, obj, issue, options):
        users_bindings = options.get('users_bindings', {})
        offset = 0
        while True:
            comments = self._client.get("/issue/{}/comment".format(issue['key']), {"startAt": offset})
            for comment in comments['comments']:
                snapshot = take_snapshot(
                    obj,
                    comment=comment['body'],
                    user=self._resolve_user(
                        comment['author'], users_bindings,
                        User(full_name=comment['author']['displayName'])
                    ),
                    delete=False
                )
                HistoryEntry.objects.filter(id=snapshot.id).update(created_at=comment['created'])

            offset += len(comments['comments'])
            if len(comments['comments']) <= comments['maxResults']:
                break

    def _create_custom_fields(self, project):
        custom_fields = []
        for model in [UserStoryCustomAttribute, TaskCustomAttribute, IssueCustomAttribute, EpicCustomAttribute]:
            model.objects.create(
                name="Due date",
                description="Due date",
                type="date",
                order=1,
                project=project
            )
            model.objects.create(
                name="Priority",
                description="Priority",
                type="text",
                order=1,
                project=project
            )
            model.objects.create(
                name="Resolution",
                description="Resolution",
                type="text",
                order=1,
                project=project
            )
            model.objects.create(
                name="Resolution date",
                description="Resolution date",
                type="date",
                order=1,
                project=project
            )
            model.objects.create(
                name="Environment",
                description="Environment",
                type="text",
                order=1,
                project=project
            )
            model.objects.create(
                name="Components",
                description="Components",
                type="text",
                order=1,
                project=project
            )
            model.objects.create(
                name="Affects Version/s",
                description="Affects Version/s",
                type="text",
                order=1,
                project=project
            )
            model.objects.create(
                name="Fix Version/s",
                description="Fix Version/s",
                type="text",
                order=1,
                project=project
            )
            model.objects.create(
                name="Links",
                description="Links",
                type="richtext",
                order=1,
                project=project
            )
        custom_fields.append({
            "history_name": "duedate",
            "jira_field_name": "duedate",
            "taiga_field_name": "Due date",
        })
        custom_fields.append({
            "history_name": "priority",
            "jira_field_name": "priority",
            "taiga_field_name": "Priority",
            "transform": lambda issue, obj: obj.get('name', None)
        })
        custom_fields.append({
            "history_name": "resolution",
            "jira_field_name": "resolution",
            "taiga_field_name": "Resolution",
            "transform": lambda issue, obj: obj.get('name', None)
        })
        custom_fields.append({
            "history_name": "Resolution date",
            "jira_field_name": "resolutiondate",
            "taiga_field_name": "Resolution date",
        })
        custom_fields.append({
            "history_name": "environment",
            "jira_field_name": "environment",
            "taiga_field_name": "Environment",
        })
        custom_fields.append({
            "history_name": "Component",
            "jira_field_name": "components",
            "taiga_field_name": "Components",
            "transform": lambda issue, obj: ", ".join([c.get('name', None) for c in obj])
        })
        custom_fields.append({
            "history_name": "Version",
            "jira_field_name": "versions",
            "taiga_field_name": "Affects Version/s",
            "transform": lambda issue, obj: ", ".join([c.get('name', None) for c in obj])
        })
        custom_fields.append({
            "history_name": "Fix Version",
            "jira_field_name": "fixVersions",
            "taiga_field_name": "Fix Version/s",
            "transform": lambda issue, obj: ", ".join([c.get('name', None) for c in obj])
        })
        custom_fields.append({
            "history_name": "Link",
            "jira_field_name": "issuelinks",
            "taiga_field_name": "Links",
            "transform": lambda issue, obj: links_to_richtext(self, issue, obj)
        })

        greenhopper_fields = {}
        for custom_field in self._client.get("/field"):
            if custom_field['custom']:
                if custom_field['schema']['custom'] == "com.pyxis.greenhopper.jira:gh-sprint":
                    greenhopper_fields["sprint"] = custom_field['id']
                elif custom_field['schema']['custom'] == "com.pyxis.greenhopper.jira:gh-epic-link":
                    greenhopper_fields["link"] = custom_field['id']
                elif custom_field['schema']['custom'] == "com.pyxis.greenhopper.jira:gh-epic-status":
                    greenhopper_fields["status"] = custom_field['id']
                elif custom_field['schema']['custom'] == "com.pyxis.greenhopper.jira:gh-epic-label":
                    greenhopper_fields["label"] = custom_field['id']
                elif custom_field['schema']['custom'] == "com.pyxis.greenhopper.jira:gh-epic-color":
                    greenhopper_fields["color"] = custom_field['id']
                elif custom_field['schema']['custom'] == "com.pyxis.greenhopper.jira:gh-lexo-rank":
                    greenhopper_fields["rank"] = custom_field['id']
                elif (
                    custom_field['name'] == "Story Points" and
                    custom_field['schema']['custom'] == 'com.atlassian.jira.plugin.system.customfieldtypes:float'
                ):
                    greenhopper_fields["points"] = custom_field['id']
                else:
                    multiline_types = [
                        "com.atlassian.jira.plugin.system.customfieldtypes:textarea"
                    ]
                    date_types = [
                        "com.atlassian.jira.plugin.system.customfieldtypes:datepicker"
                        "com.atlassian.jira.plugin.system.customfieldtypes:datetime"
                    ]
                    if custom_field['schema']['custom'] in multiline_types:
                        field_type = "multiline"
                    elif custom_field['schema']['custom'] in date_types:
                        field_type = "date"
                    else:
                        field_type = "text"

                    custom_field_data = {
                        "name": custom_field['name'][:64],
                        "description": custom_field['name'],
                        "type": field_type,
                        "order": 1,
                        "project": project
                    }

                    UserStoryCustomAttribute.objects.get_or_create(**custom_field_data)
                    TaskCustomAttribute.objects.get_or_create(**custom_field_data)
                    IssueCustomAttribute.objects.get_or_create(**custom_field_data)
                    EpicCustomAttribute.objects.get_or_create(**custom_field_data)

                    custom_fields.append({
                        "history_name": custom_field['name'],
                        "jira_field_name": custom_field['id'],
                        "taiga_field_name": custom_field['name'][:64],
                    })

        self.greenhopper_fields = greenhopper_fields
        self.custom_fields = custom_fields

    def _import_to_custom_fields(self, obj, issue, options):
        if isinstance(obj, Epic):
            custom_att_manager = obj.project.epiccustomattributes
        elif isinstance(obj, UserStory):
            custom_att_manager = obj.project.userstorycustomattributes
        elif isinstance(obj, Task):
            custom_att_manager = obj.project.taskcustomattributes
        elif isinstance(obj, Issue):
            custom_att_manager = obj.project.issuecustomattributes
        else:
            raise NotImplementedError("Not implemented custom attributes for this object ({})".format(obj))

        custom_attributes_values = {}
        for custom_field in self.custom_fields:
            data = issue['fields'].get(custom_field['jira_field_name'], None)
            if data and "transform" in custom_field:
                data = custom_field['transform'](issue, data)

            if data:
                taiga_field = custom_att_manager.get(name=custom_field['taiga_field_name'])
                custom_attributes_values[taiga_field.id] = data

        if custom_attributes_values != {}:
            obj.custom_attributes_values.attributes_values = custom_attributes_values
            obj.custom_attributes_values.save()

    def _import_attachments(self, obj, issue, options):
        users_bindings = options.get('users_bindings', {})

        for attachment in issue['fields']['attachment']:
            try:
                data = self._client.raw_get(attachment['content'])
                att = Attachment(
                    owner=self._resolve_user(attachment['author'], users_bindings, self._user),
                    project=obj.project,
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=obj.id,
                    name=attachment['filename'],
                    size=attachment['size'],
                    created_date=attachment['created'],
                    is_deprecated=False,
                )
                att.attached_file.save(attachment['filename'], ContentFile(data), save=True)
            except Exception:
                print("ERROR getting attachment url {}".format(attachment['content']))


    def _import_changelog(self, project, obj, issue, options):
        obj.cummulative_attachments = []
        for history in sorted(issue['changelog']['histories'], key=lambda h: h['created']):
            self._import_history(project, obj, history, options)

    def _import_history(self, project, obj, history, options):
        key = make_key_from_model_object(obj)
        typename = get_typename_for_model_class(obj.__class__)
        history_data = self._transform_history_data(project, obj, history, options)
        if history_data is None:
            return

        change_old = history_data['change_old']
        change_new = history_data['change_new']
        hist_type = history_data['hist_type']
        comment = history_data['comment']
        user = history_data['user']

        diff = make_diff_from_dicts(change_old, change_new)
        fdiff = FrozenDiff(key, diff, {})

        values = make_diff_values(typename, fdiff)
        values.update(history_data['update_values'])

        entry = HistoryEntry.objects.create(
            user=user,
            project_id=obj.project.id,
            key=key,
            type=hist_type,
            snapshot=None,
            diff=fdiff.diff,
            values=values,
            comment=comment,
            comment_html=mdrender(obj.project, comment),
            is_hidden=False,
            is_snapshot=False,
        )
        HistoryEntry.objects.filter(id=entry.id).update(created_at=history['created'])
        return HistoryEntry.objects.get(id=entry.id)

    def _transform_history_data(self, project, obj, history, options):
        users_bindings = options.get('users_bindings', {})

        user = {"pk": None, "name": history.get('author', {}).get('displayName', None)}
        taiga_user = self._resolve_user(history.get('author', {}), users_bindings)
        if taiga_user:
            user = {"pk": taiga_user.id, "name": taiga_user.get_full_name()}

        result = {
            "change_old": {},
            "change_new": {},
            "update_values": {},
            "hist_type": HistoryType.change,
            "comment": "",
            "user": user
        }
        custom_fields_by_names = {f["history_name"]: f for f in self.custom_fields}
        has_data = False
        for history_item in history['items']:
            if history_item['field'] == "Attachment":
                result['change_old']["attachments"] = []
                for att in obj.cummulative_attachments:
                    result['change_old']["attachments"].append({
                        "id": 0,
                        "filename": att
                    })

                if history_item['from'] is not None:
                    try:
                        idx = obj.cummulative_attachments.index(history_item['fromString'])
                        obj.cummulative_attachments.pop(idx)
                    except ValueError:
                        print("ERROR: Removing attachment that doesn't exist in the history ({})".format(history_item['fromString']))
                if history_item['to'] is not None:
                    obj.cummulative_attachments.append(history_item['toString'])

                result['change_new']["attachments"] = []
                for att in obj.cummulative_attachments:
                    result['change_new']["attachments"].append({
                        "id": 0,
                        "filename": att
                    })
                has_data = True
            elif history_item['field'] == "description":
                result['change_old']["description"] = history_item['fromString']
                result['change_new']["description"] = history_item['toString']
                result['change_old']["description_html"] = mdrender(obj.project, history_item['fromString'] or "")
                result['change_new']["description_html"] = mdrender(obj.project, history_item['toString'] or "")
                has_data = True
            elif history_item['field'] == "Epic Link":
                pass
            elif history_item['field'] == "Workflow":
                pass
            elif history_item['field'] == "Link":
                pass
            elif history_item['field'] == "labels":
                result['change_old']["tags"] = history_item['fromString'].split()
                result['change_new']["tags"] = history_item['toString'].split()
                has_data = True
            elif history_item['field'] == "Rank":
                pass
            elif history_item['field'] == "RemoteIssueLink":
                pass
            elif history_item['field'] == "Sprint":
                # Resolve through the same normalised lookup the import uses:
                # matching on the raw name missed sprints that differ only by
                # whitespace/case, and a plain .get() raised
                # MultipleObjectsReturned (aborting the whole import) whenever a
                # project ended up with two milestones of the same name.
                old_milestone = None
                if history_item['fromString']:
                    match = self._find_milestone(obj.project, history_item['fromString'])
                    old_milestone = match.id if match is not None else -1

                new_milestone = None
                if history_item['toString']:
                    match = self._find_milestone(obj.project, history_item['toString'])
                    new_milestone = match.id if match is not None else -2

                result['change_old']["milestone"] = old_milestone
                result['change_new']["milestone"] = new_milestone

                if old_milestone == -1 or new_milestone == -2:
                    result['update_values']["milestone"] = {}

                if old_milestone == -1:
                    result['update_values']["milestone"]["-1"] = history_item['fromString']
                if new_milestone == -2:
                    result['update_values']["milestone"]["-2"] = history_item['toString']
                has_data = True
            elif history_item['field'] == "status":
                if isinstance(obj, Task):
                    try:
                        old_status = obj.project.task_statuses.get(name=history_item['fromString']).id
                    except Exception:
                        old_status = -1
                    try:
                        new_status = obj.project.task_statuses.get(name=history_item['toString']).id
                    except Exception:
                        new_status = -2
                elif isinstance(obj, UserStory):
                    try:
                        old_status = obj.project.us_statuses.get(name=history_item['fromString']).id
                    except Exception:
                        old_status = -1
                    try:
                        new_status = obj.project.us_statuses.get(name=history_item['toString']).id
                    except Exception:
                        new_status = -2
                elif isinstance(obj, Issue):
                    try:
                        old_status = obj.project.issue_statuses.get(name=history_item['fromString']).id
                    except Exception:
                        old_status = -1
                    try:
                        new_status = obj.project.us_statuses.get(name=history_item['toString']).id
                    except Exception:
                        new_status = -2
                elif isinstance(obj, Epic):
                    try:
                        old_status = obj.project.epic_statuses.get(name=history_item['fromString']).id
                    except Exception:
                        old_status = -1
                    try:
                        new_status = obj.project.epic_statuses.get(name=history_item['toString']).id
                    except Exception:
                        new_status = -2

                if old_status == -1 or new_status == -2:
                    result['update_values']["status"] = {}

                if old_status == -1:
                    result['update_values']["status"]["-1"] = history_item['fromString']
                if new_status == -2:
                    result['update_values']["status"]["-2"] = history_item['toString']

                result['change_old']["status"] = old_status
                result['change_new']["status"] = new_status
                has_data = True
            elif history_item['field'] == "Story Points":
                old_points = None
                if history_item['fromString']:
                    estimation = float(history_item['fromString'])
                    (old_points, _) = Points.objects.get_or_create(
                        project=project,
                        value=estimation,
                        defaults={
                            "name": str(estimation),
                            "order": estimation,
                        }
                    )
                    old_points = old_points.id
                new_points = None
                if history_item['toString']:
                    estimation = float(history_item['toString'])
                    (new_points, _) = Points.objects.get_or_create(
                        project=project,
                        value=estimation,
                        defaults={
                            "name": str(estimation),
                            "order": estimation,
                        }
                    )
                    new_points = new_points.id
                result['change_old']["points"] = {project.roles.get(slug="main").id: old_points}
                result['change_new']["points"] = {project.roles.get(slug="main").id: new_points}
                has_data = True
            elif history_item['field'] == "summary":
                result['change_old']["subject"] = history_item['fromString']
                result['change_new']["subject"] = history_item['toString']
                has_data = True
            elif history_item['field'] == "Epic Color":
                if isinstance(obj, Epic):
                    result['change_old']["color"] = EPIC_COLORS.get(history_item['fromString'], None)
                    result['change_new']["color"] = EPIC_COLORS.get(history_item['toString'], None)
                    Epic.objects.filter(id=obj.id).update(
                        color=EPIC_COLORS.get(history_item['toString'], "#999999")
                    )
                    has_data = True
            elif history_item['field'] == "assignee":
                # -1 / -2 are Taiga's "this user could not be resolved"
                # sentinels; the display name is then carried in update_values
                # so the change still reads correctly in the UI.
                old_assigned_to = None
                if history_item['from'] is not None:
                    old_user = self._resolve_user_ref(history_item['from'],
                                                      history_item.get('fromString'),
                                                      users_bindings)
                    old_assigned_to = old_user.id if old_user is not None else -1

                new_assigned_to = None
                if history_item['to'] is not None:
                    new_user = self._resolve_user_ref(history_item['to'],
                                                      history_item.get('toString'),
                                                      users_bindings)
                    new_assigned_to = new_user.id if new_user is not None else -2

                result['change_old']["assigned_to"] = old_assigned_to
                result['change_new']["assigned_to"] = new_assigned_to

                if old_assigned_to == -1 or new_assigned_to == -2:
                    result['update_values'].setdefault("users", {})

                if old_assigned_to == -1:
                    result['update_values']["users"]["-1"] = history_item['fromString']
                if new_assigned_to == -2:
                    result['update_values']["users"]["-2"] = history_item['toString']
                has_data = True
            elif history_item['field'] in custom_fields_by_names:
                custom_field = custom_fields_by_names[history_item['field']]
                if isinstance(obj, Task):
                    field_obj = obj.project.taskcustomattributes.get(name=custom_field['taiga_field_name'])
                elif isinstance(obj, UserStory):
                    field_obj = obj.project.userstorycustomattributes.get(name=custom_field['taiga_field_name'])
                elif isinstance(obj, Issue):
                    field_obj = obj.project.issuecustomattributes.get(name=custom_field['taiga_field_name'])
                elif isinstance(obj, Epic):
                    field_obj = obj.project.epiccustomattributes.get(name=custom_field['taiga_field_name'])

                result['change_old']["custom_attributes"] = [{
                    "name": custom_field['taiga_field_name'],
                    "value": history_item['fromString'],
                    "id": field_obj.id
                }]
                result['change_new']["custom_attributes"] = [{
                    "name": custom_field['taiga_field_name'],
                    "value": history_item['toString'],
                    "id": field_obj.id
                }]
                has_data = True

        if not has_data:
            return None

        return result

    # ------------------------------------------------------------------
    # Sprint (Jira) -> Milestone (Taiga)
    # ------------------------------------------------------------------

    @staticmethod
    def _sprint_key(name):
        """Comparison key for a sprint name: whitespace-collapsed, casefolded.

        Jira sprint names routinely differ only by stray or doubled whitespace
        and by capitalisation ("Sprint 1" / "sprint 1" / "Sprint  1"). Matching
        on the raw string created a second Taiga milestone for what is really
        one Jira sprint, so every lookup goes through this key instead.
        """
        return re.sub(r"\s+", " ", (name or "")).strip().casefold()

    @staticmethod
    def _clean_sprint_name(name):
        """The name we actually store: same normalisation, original casing."""
        return re.sub(r"\s+", " ", (name or "")).strip()

    def _milestone_index(self, project):
        """Name-key -> milestone map for a project, built once and kept warm.

        The importer is the only writer during an import, so caching is safe and
        saves one query per issue. Pre-existing milestones are indexed too, so
        an import into a project that already has sprints reuses them instead of
        duplicating them.
        """
        cache = getattr(self, "_milestone_cache", None)
        if cache is None:
            cache = self._milestone_cache = {}
        index = cache.get(project.id)
        if index is None:
            index = {}
            for milestone in project.milestones.all().order_by("id"):
                index.setdefault(self._sprint_key(milestone.name), milestone)
            cache[project.id] = index
        return index

    def _find_milestone(self, project, name):
        """Existing milestone for a Jira sprint name, or None."""
        key = self._sprint_key(name)
        if not key:
            return None
        return self._milestone_index(project).get(key)

    def _sprint_attrs(self, sprint):
        """Normalise a Jira sprint value to name/start/end/state.

        Jira Cloud returns sprint objects (dicts); older Jira Server returns the
        greenhopper toString blob, e.g. "...Sprint@1a2b[id=5,rapidViewId=1,
        state=CLOSED,name=Sprint 1,startDate=2026-01-06T02:00:00.000Z,...]".
        Server writes missing values as the literal "<null>".
        """
        empty = {"name": None, "start": None, "end": None, "state": None}

        if isinstance(sprint, dict):
            return {
                "name": sprint.get('name'),
                "start": sprint.get('startDate'),
                "end": sprint.get('endDate') or sprint.get('completeDate'),
                "state": sprint.get('state'),
            }

        if isinstance(sprint, str):
            def field(key):
                # anchor on "[" or "," so a key never matches inside another one
                match = re.search(r"(?:^|[,\[]){}=([^,\]]*)".format(key), sprint)
                value = match.group(1).strip() if match else None
                if value in (None, "", "<null>", "null"):
                    return None
                return value

            return {
                "name": field("name"),
                "start": field("startDate"),
                "end": field("endDate") or field("completeDate"),
                "state": field("state"),
            }

        return empty

    def _sprint_name(self, sprint):
        return self._sprint_attrs(sprint)["name"]

    def _issue_sprints(self, issue):
        """Every sprint value carried by a Jira issue, oldest first.

        The greenhopper sprint custom field holds the full ordered list of
        sprints the issue has belonged to, closed ones included. It is more
        reliable than the Agile API's `fields.sprint`, which is null for issues
        whose only sprint is already closed -- the usual case for migrated or
        historical boards, where every story otherwise fell back to the backlog.
        """
        fields = issue.get('fields') or {}
        sprints = []

        sprint_field = getattr(self, "greenhopper_fields", {}).get("sprint")
        if sprint_field:
            value = fields.get(sprint_field)
            if value:
                sprints = list(value) if isinstance(value, list) else [value]

        if not sprints:
            active = fields.get('sprint')
            if active:
                sprints = list(active) if isinstance(active, list) else [active]

        if not sprints:
            closed = fields.get('closedSprints')
            if closed:
                sprints = list(closed) if isinstance(closed, list) else [closed]

        return sprints

    def _resolve_milestone(self, project, issue):
        """Milestone matching the issue's current Jira sprint, created if needed.

        Walks the sprint list backwards: the last entry is the issue's current
        sprint, but an entry can be unparseable or nameless, and falling
        straight back to the backlog would silently drop a sprint name we do
        have. The first entry that yields a name wins.
        """
        for sprint in reversed(self._issue_sprints(issue)):
            attrs = self._sprint_attrs(sprint)
            if not attrs["name"]:
                continue
            milestone = self._get_or_create_milestone(
                project, attrs["name"], attrs["start"], attrs["end"], attrs["state"])
            if milestone is not None:
                return milestone
        return None

    @staticmethod
    def _sprint_dates(start_datetime, end_datetime):
        """Jira start/end -> a (start, end) pair Taiga will accept.

        Taiga requires both dates and rejects a sprint that finishes before it
        starts. A sprint with only one of the two (common for future sprints
        that were never started) keeps its real date on both ends rather than
        being stamped with today's date.
        """
        start = (start_datetime or "")[:10] or None
        end = (end_datetime or "")[:10] or None

        if not start and not end:
            today = datetime.date.today().isoformat()
            return today, today
        if not start:
            start = end
        if not end:
            end = start
        if end < start:
            end = start
        return start, end

    def _get_or_create_milestone(self, project, name, start_datetime=None,
                                 end_datetime=None, state=None):
        """Return the milestone for a Jira sprint, creating it only if absent.

        Reuses any milestone whose name matches (whitespace- and case-
        insensitively), so re-running an import, a sprint carried over from
        another board, and a sprint listed by several boards all land on one
        milestone instead of duplicates. Milestones this import created are
        enriched in place when a later, better-informed Jira payload turns up
        (the board sprint list carries real dates and state; an issue's sprint
        blob often does not). Falls back to None only if creation genuinely
        fails, so a story is never lost to an import error -- it just stays in
        the backlog, as before.
        """
        clean_name = self._clean_sprint_name(name)
        if not clean_name:
            return None

        key = self._sprint_key(clean_name)
        existing = self._find_milestone(project, clean_name)
        if existing is not None:
            self._enrich_milestone(existing, start_datetime, end_datetime, state)
            return existing

        start_date, end_date = self._sprint_dates(start_datetime, end_datetime)

        base_slug = slugify(clean_name) or "sprint"
        slug = base_slug
        suffix = 1
        while project.milestones.filter(slug=slug).exists():
            suffix += 1
            slug = "{}-{}".format(base_slug, suffix)

        try:
            milestone = Milestone.objects.create(
                name=clean_name,
                slug=slug,
                owner=self._user,
                project=project,
                estimated_start=start_date,
                estimated_finish=end_date,
                closed=str(state).upper() == "CLOSED",
            )
        except Exception:
            # Never let a milestone problem abort the whole import; leave the
            # story in the backlog instead. Re-read in case of a race.
            fallback = project.milestones.filter(name=clean_name).first()
            if fallback is not None:
                self._milestone_index(project)[key] = fallback
            return fallback

        Milestone.objects.filter(id=milestone.id).update(
            created_date=start_datetime or timezone.now(),
            modified_date=start_datetime or timezone.now(),
        )

        self._milestone_index(project)[key] = milestone
        self._imported_milestone_ids().add(milestone.id)
        return milestone

    def _imported_milestone_ids(self):
        ids = getattr(self, "_imported_milestones", None)
        if ids is None:
            ids = self._imported_milestones = set()
        return ids

    def _enrich_milestone(self, milestone, start_datetime, end_datetime, state):
        """Fill in dates/state on a milestone this import created.

        A sprint first seen on an issue's greenhopper blob can arrive without
        dates; the board sprint list that comes later has them. Only milestones
        created by this import are touched, so sprints the Taiga project already
        had are never rewritten.
        """
        if milestone.id not in self._imported_milestone_ids():
            return
        if not (start_datetime or end_datetime or state):
            return

        updates = {}
        if start_datetime or end_datetime:
            start_date, end_date = self._sprint_dates(start_datetime, end_datetime)
            if str(milestone.estimated_start) != start_date:
                updates["estimated_start"] = start_date
            if str(milestone.estimated_finish) != end_date:
                updates["estimated_finish"] = end_date
        if state:
            closed = str(state).upper() == "CLOSED"
            if milestone.closed != closed:
                updates["closed"] = closed

        if not updates:
            return

        try:
            Milestone.objects.filter(id=milestone.id).update(**updates)
        except Exception:
            return
        for field, value in updates.items():
            setattr(milestone, field, value)

    def _import_board_sprints(self, project, board_id):
        """Create a Taiga milestone for every sprint on a Jira board, including
        the closed ones and those past the API's first page.

        A board with no sprint endpoint (kanban) or one the token cannot read is
        skipped: sprints are worth importing, but never at the cost of aborting
        the whole import.
        """
        offset = 0
        seen_pages = 0
        while True:
            try:
                sprints = self._client.get_agile(
                    "/board/{}/sprint".format(board_id), {"startAt": offset})
            except Exception:
                return

            values = (sprints or {}).get('values') or []
            for sprint in values:
                self._get_or_create_milestone(
                    project,
                    sprint.get('name'),
                    sprint.get('startDate'),
                    sprint.get('endDate') or sprint.get('completeDate'),
                    sprint.get('state'),
                )

            page_size = (sprints or {}).get('maxResults') or 0
            seen_pages += 1
            # `isLast` is authoritative when present; the length check covers
            # older Jira. A zero/absent page size would never advance the
            # offset, so stop rather than loop forever.
            if (sprints or {}).get('isLast', True):
                return
            if not page_size or len(values) < page_size or seen_pages > 200:
                return
            offset += page_size

    def _import_project_sprints(self, project, jira_project_id):
        """Create the sprints of every board attached to a Jira project.

        The project importer has no board of its own, so without this only
        sprints that happen to hang off an imported issue would ever exist --
        empty and future sprints would be missing from the Scrum section. Boards
        the token can't read, and kanban boards with no sprint endpoint, are
        skipped rather than aborting the import.
        """
        offset = 0
        seen_pages = 0
        while True:
            try:
                boards = self._client.get_agile(
                    "/board", {"projectKeyOrId": jira_project_id, "startAt": offset})
            except Exception:
                # No Agile API (Jira Core), or no board permission.
                return

            values = (boards or {}).get('values') or []
            for board in values:
                if not board.get('id'):
                    continue
                try:
                    self._import_board_sprints(project, board['id'])
                except Exception:
                    continue

            page_size = (boards or {}).get('maxResults') or 0
            seen_pages += 1
            if (boards or {}).get('isLast', True):
                return
            if not page_size or len(values) < page_size or seen_pages > 200:
                return
            offset += page_size

    def _activate_sprints_module(self, project):
        """Sprints live under Taiga's backlog module. A project imported from a
        kanban board or with the kanban template has it switched off, which
        would hide every milestone we just created.
        """
        if not project.milestones.exists():
            return
        if project.is_backlog_activated:
            return
        Project.objects.filter(id=project.id).update(is_backlog_activated=True)
        project.is_backlog_activated = True

    def _cleanup(self, project, options):
        for epic_custom_field in project.epiccustomattributes.all():
            if project.epics.filter(custom_attributes_values__attributes_values__has_key=str(epic_custom_field.id)).count() == 0:
                epic_custom_field.delete()
        for us_custom_field in project.userstorycustomattributes.all():
            if project.user_stories.filter(custom_attributes_values__attributes_values__has_key=str(us_custom_field.id)).count() == 0:
                us_custom_field.delete()
        for task_custom_field in project.taskcustomattributes.all():
            if project.tasks.filter(custom_attributes_values__attributes_values__has_key=str(task_custom_field.id)).count() == 0:
                task_custom_field.delete()
        for issue_custom_field in project.issuecustomattributes.all():
            if project.issues.filter(custom_attributes_values__attributes_values__has_key=str(issue_custom_field.id)).count() == 0:
                issue_custom_field.delete()

    @classmethod
    def get_auth_url(cls, server, consumer_key, key_cert_data, verify=None):
        if verify is None:
            verify = server.startswith('https')

        callback_uri = resolve_front_url("project-import-jira", quote_plus(server))
        oauth = OAuth1(consumer_key, signature_method=SIGNATURE_RSA, rsa_key=key_cert_data, callback_uri=callback_uri)

        r = requests.post(
            server + '/plugins/servlet/oauth/request-token', verify=verify, auth=oauth)
        if r.status_code != 200:
            raise exceptions.InvalidServiceConfiguration()
        request = dict(parse_qsl(r.text))
        request_token = request['oauth_token']
        request_token_secret = request['oauth_token_secret']

        return (
            request_token,
            request_token_secret,
            '{}/plugins/servlet/oauth/authorize?oauth_token={}'.format(server, request_token)
        )

    @classmethod
    def get_access_token(cls, server, consumer_key, key_cert_data, request_token, request_token_secret, request_verifier, verify=False):
        callback_uri = resolve_front_url("project-import-jira", quote_plus(server))
        oauth = OAuth1(
            consumer_key,
            signature_method=SIGNATURE_RSA,
            callback_uri=callback_uri,
            rsa_key=key_cert_data,
            resource_owner_key=request_token,
            resource_owner_secret=request_token_secret,
            verifier=request_verifier,
        )
        r = requests.post(server + '/plugins/servlet/oauth/access-token', verify=verify, auth=oauth)
        access = dict(parse_qsl(r.text))

        return {
            'access_token': access['oauth_token'],
            'access_token_secret': access['oauth_token_secret'],
            'consumer_key': consumer_key,
            'key_cert': key_cert_data
        }
