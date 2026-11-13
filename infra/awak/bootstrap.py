"""Create the Taiga users and projects the Awak loop needs (local dev stack).

Idempotent. Run inside kemudi-back:

    docker compose -f infra/docker-compose.dev.yml --env-file infra/.env exec -T \
      -e KEMUDI_AWAK_PASSWORD -e KEMUDI_QA_PASSWORD -e AWAK_PM=webdev \
      kemudi-back python manage.py shell < infra/awak/bootstrap.py

- `awak` (bot) and `awak-qa` (QA) users, with passwords from the environment.
- Project `kemudi` (scrum template), owned by the PM user (AWAK_PM), with
  `awak` as a member. Awak's work happens here.
- Project `awak-qa-sandbox`, owned by `awak-qa`, a throwaway place for QA
  specs to create and edit things. `awak-qa` is not a member of `kemudi`.
"""

import os

from taiga.projects.models import Membership, Project, ProjectTemplate
from taiga.users.models import Role, User


def user(username: str, full_name: str, password: str) -> User:
    if not password:
        raise SystemExit(f"set the password for {username} in the environment")
    u = User.objects.filter(username=username).first()
    if u is None:
        u = User(username=username, email=f"{username}@kemudi.local", full_name=full_name)
    u.full_name = full_name
    u.is_active = True
    u.set_password(password)
    u.save()
    return u


def project(slug: str, name: str, owner: User, description: str) -> Project:
    p = Project.objects.filter(slug=slug).first()
    if p is None:
        p = Project(name=name, slug=slug, description=description, owner=owner,
                    creation_template=ProjectTemplate.objects.get(slug="scrum"),
                    is_private=True)
        p.save()
    return p


def member(p: Project, u: User, role_slug: str = "back", admin: bool = False) -> None:
    role = Role.objects.filter(project=p, slug=role_slug).first() or p.roles.first()
    m, _ = Membership.objects.get_or_create(
        project=p, user=u, defaults={"role": role, "email": u.email, "is_admin": admin})
    if m.is_admin != admin and not p.owner_id == u.id:
        m.is_admin = admin
        m.save()


awak = user("awak", "Awak", os.environ.get("KEMUDI_AWAK_PASSWORD", ""))
qa = user("awak-qa", "Awak QA", os.environ.get("KEMUDI_QA_PASSWORD", ""))
pm = User.objects.get(username=os.environ.get("AWAK_PM", "webdev"))

kemudi = project("kemudi", "Kemudi", pm,
                 "Kemudi's own development, run through the Awak loop.")
member(kemudi, awak)
sandbox = project("awak-qa-sandbox", "Awak QA sandbox", qa,
                  "Throwaway data for Awak's QA runs. Anything here may be deleted.")

statuses = list(kemudi.us_statuses.values_list("slug", flat=True))
print("kemudi user story statuses:", statuses)
for needed in ("new", "ready", "in-progress", "ready-for-test", "done"):
    if needed not in statuses:
        print(f"WARNING: status {needed!r} missing in project kemudi")
print("ok: users awak, awak-qa; projects kemudi, awak-qa-sandbox")
