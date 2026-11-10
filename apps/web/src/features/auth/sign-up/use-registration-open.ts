import { useQuery } from '@tanstack/react-query'
import { registrationOpen } from '@/lib/taiga/client'

/** Whether this server allows open sign-up (asked once per visit). */
export function useRegistrationOpen() {
  return useQuery({
    queryKey: ['registration-open'],
    staleTime: Infinity,
    queryFn: registrationOpen,
  })
}
