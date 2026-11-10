import { avatarUrl, initials } from '@/lib/taiga/client'
import { cn } from '@/lib/utils'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'

type UserAvatarProps = {
  user: { photo: string | null; full_name_display: string; color?: string }
  className?: string
}

/** Member photo, or initials on the member's Taiga colour. */
export function UserAvatar({ user, className }: UserAvatarProps) {
  return (
    <Avatar className={cn('size-6', className)}>
      <AvatarImage src={avatarUrl(user)} alt='' />
      <AvatarFallback
        className='text-[0.625rem] font-semibold text-white'
        style={{ backgroundColor: user.color ?? 'var(--muted-foreground)' }}
      >
        {initials(user.full_name_display)}
      </AvatarFallback>
    </Avatar>
  )
}
