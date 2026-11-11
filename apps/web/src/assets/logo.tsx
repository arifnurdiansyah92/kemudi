import { cn } from '@/lib/utils'

const SPOKES = [0, 45, 90, 135, 180, 225, 270, 315]

/** Kemudi mark: a ship's helm, eight spokes around a hub. */
export function Logo({ className, ...props }: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox='0 0 24 24'
      fill='none'
      stroke='currentColor'
      strokeWidth={1.75}
      strokeLinecap='round'
      className={cn('size-6', className)}
      aria-hidden='true'
      {...props}
    >
      <circle cx='12' cy='12' r='6.5' />
      <circle cx='12' cy='12' r='2' />
      {SPOKES.map((deg) => (
        <line
          key={deg}
          x1='12'
          y1='3'
          x2='12'
          y2='10'
          transform={`rotate(${deg} 12 12)`}
        />
      ))}
    </svg>
  )
}
