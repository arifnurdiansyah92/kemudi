import { createFileRoute } from '@tanstack/react-router'
import { TransferOwnership } from '@/features/project/transfer'

export const Route = createFileRoute('/_authenticated/p/$slug/transfer/$token')(
  {
    component: function Transfer() {
      const { token } = Route.useParams()
      return <TransferOwnership token={token} />
    },
  }
)
