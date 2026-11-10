/**
 * Shapes returned by the kemudi-back REST API (taiga-back 6.10).
 * Only the fields the UI reads are typed; the API returns more.
 */

export type Id = number

export interface AuthUser {
  id: Id
  username: string
  full_name: string
  full_name_display: string
  email: string
  photo: string | null
  big_photo: string | null
  color: string
  gravatar_id: string
  lang: string
  timezone: string
  is_active: boolean
}

export interface AuthResponse extends AuthUser {
  auth_token: string
  refresh: string
}

export interface UserExtraInfo {
  id: Id
  username: string
  full_name_display: string
  photo: string | null
  big_photo?: string | null
  gravatar_id: string
  is_active: boolean
}

export interface Member {
  id: Id
  username: string
  full_name: string
  full_name_display: string
  role: Id
  role_name: string
  color: string
  photo: string | null
  gravatar_id: string
  is_active: boolean
}

export interface Role {
  id: Id
  name: string
  slug: string
  order: number
  computable: boolean
}

export interface Point {
  id: Id
  name: string
  order: number
  value: number | null
}

export interface Status {
  id: Id
  name: string
  slug: string
  order: number
  color: string
  is_closed: boolean
  is_archived?: boolean
  wip_limit?: number | null
}

export interface ProjectSummary {
  id: Id
  name: string
  slug: string
  description: string
  logo_small_url: string | null
  is_private: boolean
  is_backlog_activated: boolean
  is_kanban_activated: boolean
  is_issues_activated: boolean
  i_am_admin: boolean
  i_am_member: boolean
  total_milestones: number | null
  total_story_points: number | null
  modified_date: string
  my_permissions: string[]
  members: Id[]
}

export interface Project extends Omit<ProjectSummary, 'members'> {
  members: Member[]
  roles: Role[]
  points: Point[]
  us_statuses: Status[]
  task_statuses: Status[]
  default_us_status: Id | null
  default_task_status: Id | null
  default_points: Id | null
  tags_colors: Record<string, string | null>
}

export type Tag = [name: string, color: string | null]

export interface StatusExtraInfo {
  name: string
  color: string
  is_closed: boolean
}

export interface UserStory {
  id: Id
  ref: number
  version: number
  project: Id
  subject: string
  status: Id
  status_extra_info: StatusExtraInfo
  milestone: Id | null
  milestone_name: string | null
  milestone_slug: string | null
  assigned_to: Id | null
  assigned_to_extra_info: UserExtraInfo | null
  assigned_users: Id[]
  owner: Id
  owner_extra_info: UserExtraInfo | null
  points: Record<string, Id>
  total_points: number | null
  tags: Tag[]
  is_blocked: boolean
  blocked_note: string
  is_closed: boolean
  backlog_order: number
  sprint_order: number
  kanban_order: number
  total_comments: number
  due_date: string | null
  created_date: string
  modified_date: string
  tasks?: { id: Id; ref: number; subject: string; is_closed: boolean }[]
}

export interface UserStoryDetail extends UserStory {
  description: string
  description_html: string
  blocked_note_html: string
}

export interface Milestone {
  id: Id
  name: string
  slug: string
  project: Id
  estimated_start: string
  estimated_finish: string
  closed: boolean
  order: number
  total_points: number | null
  closed_points: number | null
  user_stories: UserStory[]
}

export interface Task {
  id: Id
  ref: number
  version: number
  project: Id
  user_story: Id | null
  milestone: Id | null
  subject: string
  status: Id
  status_extra_info: StatusExtraInfo
  is_closed: boolean
  assigned_to: Id | null
  assigned_to_extra_info: UserExtraInfo | null
  us_order: number
  taskboard_order: number
}

export interface HistoryEntry {
  id: string
  user: {
    pk: Id
    username: string
    name: string
    photo: string | null
    gravatar_id: string
    is_active: boolean
  }
  created_at: string
  type: number
  comment: string
  comment_html: string
  delete_comment_date: string | null
  edit_comment_date: string | null
}
