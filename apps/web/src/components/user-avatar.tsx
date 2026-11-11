import { avatarUrl, initials } from '@/lib/taiga/client'
import { cn } from '@/lib/utils'
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar'

type UserAvatarProps = {
  user: { photo: string | null; full_name_display: string; color?: string }
  className?: string
}

/**
 * Taiga gives each member a random colour, often a light one (lime,
 * yellow). Pick ink or white initials by the colour's luminance so the
 * initials stay readable on any of them.
 */
function readableOn(hex?: string) {
  const m = hex?.match(/^#?([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i)
  if (!m) return 'text-white'
  const [r, g, b] = m.slice(1).map((c) => {
    const v = parseInt(c, 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
  // White wins below ~0.18 luminance; above it, dark text has more contrast.
  return luminance > 0.18 ? 'text-[oklch(0.22_0.045_255)]' : 'text-white'
}

/** Member photo, or initials on the member's Taiga colour. */
export function UserAvatar({ user, className }: UserAvatarProps) {
  return (
    <Avatar className={cn('size-6', className)}>
      <AvatarImage src={avatarUrl(user)} alt='' />
      <AvatarFallback
        className={cn(
          'text-[0.6875rem] font-semibold',
          user.color ? readableOn(user.color) : 'text-white'
        )}
        style={{ backgroundColor: user.color ?? 'var(--muted-foreground)' }}
      >
        {initials(user.full_name_display)}
      </AvatarFallback>
    </Avatar>
  )
}
