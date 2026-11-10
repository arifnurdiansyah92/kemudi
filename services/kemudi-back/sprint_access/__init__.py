# -*- coding: utf-8 -*-
"""
Per-role sprint access for Taiga (overlay, no schema change).

Admin > Permissions > Sprints gets a multi-select of sprints per role. The
selection is stored in ``Role.permissions`` as ``sprint:<milestone_id>`` entries
(the front-end patch sends ``{"sprint_access": [ids]}`` on PATCH /roles/<id>).

Semantics
- A role with no ``sprint:*`` entry sees every sprint (stock behaviour).
- A role with entries only sees those milestones; user stories / tasks / issues
  that belong to any *other* milestone of that project are hidden as well.
  Items without milestone (backlog) are never affected.
- Project admins / owners (membership.is_admin) and superusers are never restricted.

Hooks (monkeypatched from taiga/wsgi.py after Django setup):
- Milestone/UserStory/Task/IssueViewSet.get_queryset -> list, retrieve, by_ref, stats, ...
- ProjectViewSet.retrieve (+ by_slug)                -> "milestones" of the project detail
                                                        (sidebar "Scrum" sprint menu)
- ResourcePermission.check_permissions              -> 403 on any object-level action that
                                                        bypasses get_queryset (e.g. milestone stats)
- SearchViewSet                                      -> global search results
- RolesViewSet.create/update/pre_save                -> keep/replace the sprint:* entries
  (stock front rebuilds ``permissions`` from the checkboxes on every toggle, and
  the choices validation in pre_save would reject our entries otherwise).
"""
import logging

from django.apps import apps
from django.db.models import Q

logger = logging.getLogger(__name__)

PREFIX = "sprint:"


def sprint_ids(permissions):
    ids = set()
    for p in permissions or []:
        if isinstance(p, str) and p.startswith(PREFIX) and p[len(PREFIX):].isdigit():
            ids.add(int(p[len(PREFIX):]))
    return ids


def strip(permissions):
    return [p for p in permissions or [] if not (isinstance(p, str) and p.startswith(PREFIX))]


def restrictions_for(request):
    """{project_id: set(milestone_id)} for every membership of request.user whose role
    restricts sprints. Cached on the request."""
    cached = getattr(request, "_sprint_access", None)
    if cached is not None:
        return cached
    result = {}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and not user.is_superuser:
        Membership = apps.get_model("projects", "Membership")
        qs = (Membership.objects.filter(user=user, is_admin=False, role__isnull=False)
              .select_related("role"))
        for m in qs:
            ids = sprint_ids(m.role.permissions)
            if ids:
                result[m.project_id] = ids
    try:
        request._sprint_access = result
    except Exception:
        pass
    return result


def _milestone_field(model):
    if model._meta.label == "milestones.Milestone":
        return "id"
    if any(f.name == "milestone" for f in model._meta.fields):
        return "milestone_id"
    return None


def restrict_queryset(request, qs):
    field = _milestone_field(qs.model)
    if field is None:
        return qs
    restr = restrictions_for(request)
    if not restr:
        return qs
    cond = ~Q(project_id__in=list(restr))
    if field == "milestone_id":
        cond |= Q(milestone_id__isnull=True)
    for pid, ids in restr.items():
        cond |= Q(project_id=pid, **{field + "__in": list(ids)})
    return qs.filter(cond)


def restrict_milestone_dicts(request, project_id, milestones):
    restr = restrictions_for(request)
    allowed = restr.get(project_id)
    if allowed is None or not milestones:
        return milestones
    return [m for m in milestones if m.get("id") in allowed]


def restrict_objects(request, objs):
    """Python-side variant of restrict_queryset for already-sliced querysets / lists."""
    restr = restrictions_for(request)
    if not restr:
        return objs
    out = []
    for o in objs:
        allowed = restr.get(getattr(o, "project_id", None))
        mid = getattr(o, "milestone_id", None)
        if allowed is None or mid is None or mid in allowed:
            out.append(o)
    return out


def object_allowed(request, obj):
    """False when obj is (or belongs to) a milestone the requesting user may not see."""
    if obj is None:
        return True
    restr = restrictions_for(request)
    if not restr:
        return True
    allowed = restr.get(getattr(obj, "project_id", None))
    if allowed is None:
        return True
    label = obj._meta.label if hasattr(obj, "_meta") else ""
    mid = obj.id if label == "milestones.Milestone" else getattr(obj, "milestone_id", None)
    return mid is None or mid in allowed


def _wrap_get_queryset(viewset_cls):
    orig = viewset_cls.get_queryset

    def get_queryset(self):
        qs = orig(self)
        try:
            return restrict_queryset(self.request, qs)
        except Exception:
            logger.exception("sprint_access: get_queryset filter failed (%s)", viewset_cls.__name__)
            return qs

    viewset_cls.get_queryset = get_queryset


def install():
    from taiga.projects.api import ProjectViewSet
    from taiga.projects.milestones.api import MilestoneViewSet
    from taiga.projects.userstories.api import UserStoryViewSet
    from taiga.projects.tasks.api import TaskViewSet
    from taiga.projects.issues.api import IssueViewSet
    from taiga.searches.api import SearchViewSet
    from taiga.users.api import RolesViewSet

    # 1. querysets: list, retrieve, by_ref, stats, update, delete ... all start here -------
    for cls in (MilestoneViewSet, UserStoryViewSet, TaskViewSet, IssueViewSet):
        _wrap_get_queryset(cls)

    # 1b. object-level permission check: catches actions that fetch the object without
    #     get_queryset (e.g. milestones/<id>/stats uses get_object_or_error) -> 403.
    from taiga.base.api.permissions import ResourcePermission
    _orig_check = ResourcePermission.check_permissions

    def check_permissions(self, action, obj=None):
        ok = _orig_check(self, action, obj)
        if ok and obj is not None:
            try:
                return object_allowed(self.request, obj)
            except Exception:
                logger.exception("sprint_access: object check failed")
        return ok

    ResourcePermission.check_permissions = check_permissions

    # 2. project detail -> "milestones" (sidebar Scrum menu). The serializer is serpy-compiled
    #    at class creation, so patch the response instead of ProjectDetailSerializer.get_milestones.
    _orig_retrieve = ProjectViewSet.retrieve

    def retrieve(self, request, *args, **kwargs):
        resp = _orig_retrieve(self, request, *args, **kwargs)
        try:
            data = getattr(resp, "data", None)
            if isinstance(data, dict) and isinstance(data.get("milestones"), list):
                before = data["milestones"]
                after = restrict_milestone_dicts(request, data.get("id"), before)
                if after is not before:
                    data["milestones"] = after
                    # keep the "N sprints" counters of the backlog header consistent
                    data["total_milestones"] = len(after)
                    data["total_closed_milestones"] = sum(1 for m in after if m.get("closed"))
        except Exception:
            logger.exception("sprint_access: project milestones filter failed")
        return resp

    ProjectViewSet.retrieve = retrieve

    # 3. search (services slice the queryset, so filter the objects) ----------------------
    from taiga.searches import services as search_services
    from taiga.searches import serializers as search_serializers

    _orig_search_list = SearchViewSet.list

    def search_list(self, request, **kwargs):
        restrictions_for(request)  # warm the cache on the request thread
        return _orig_search_list(self, request, **kwargs)

    def _search_user_stories(self, project, text):
        objs = restrict_objects(self.request, search_services.search_user_stories(project, text))
        return search_serializers.UserStorySearchResultsSerializer(objs, many=True).data

    def _search_tasks(self, project, text):
        objs = restrict_objects(self.request, search_services.search_tasks(project, text))
        return search_serializers.TaskSearchResultsSerializer(objs, many=True).data

    def _search_issues(self, project, text):
        objs = restrict_objects(self.request, search_services.search_issues(project, text))
        return search_serializers.IssueSearchResultsSerializer(objs, many=True).data

    SearchViewSet.list = search_list
    SearchViewSet._search_user_stories = _search_user_stories
    SearchViewSet._search_tasks = _search_tasks
    SearchViewSet._search_issues = _search_issues

    # 4. roles: keep / replace sprint:* entries ------------------------------------------
    #    The validator marks every field present in the payload as required, which turns
    #    the model choices validation on -> strip our entries from the payload first
    #    (the stock front sends the whole role, entries included, when renaming it).
    def _clean_payload(request):
        try:
            data = request.DATA
            if isinstance(data, dict) and isinstance(data.get("permissions"), list):
                data["permissions"] = strip(data["permissions"])
        except Exception:
            logger.exception("sprint_access: could not clean role payload")

    for name in ("create", "update", "partial_update"):
        orig = getattr(RolesViewSet, name)

        def make(orig):
            def method(self, request, *args, **kwargs):
                _clean_payload(request)
                return orig(self, request, *args, **kwargs)
            return method

        setattr(RolesViewSet, name, make(orig))

    _orig_pre_save = RolesViewSet.pre_save

    def pre_save(self, obj):
        data = getattr(self.request, "DATA", None) or {}
        obj.permissions = strip(obj.permissions)   # stock validation must not see our entries
        _orig_pre_save(self, obj)
        if "sprint_access" in data:
            raw = data.get("sprint_access") or []
            if not isinstance(raw, (list, tuple)):
                raw = [raw]
            ids = sorted({int(x) for x in raw if str(x).isdigit()})
            if ids and obj.project_id:
                Milestone = apps.get_model("milestones", "Milestone")
                valid = set(Milestone.objects.filter(project_id=obj.project_id, id__in=ids)
                            .values_list("id", flat=True))
                ids = [i for i in ids if i in valid]
            extra = ["%s%d" % (PREFIX, i) for i in ids]
        elif obj.pk:
            Role = apps.get_model("users", "Role")
            current = Role.objects.filter(pk=obj.pk).values_list("permissions", flat=True).first()
            extra = [p for p in (current or []) if p.startswith(PREFIX)]
        else:
            extra = []
        obj.permissions = strip(obj.permissions) + extra

    RolesViewSet.pre_save = pre_save
    logger.info("sprint_access: installed")
