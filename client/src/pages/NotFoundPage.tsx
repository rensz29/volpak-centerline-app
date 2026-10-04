import { Compass } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/shared/EmptyState'
import { Button } from '@/components/ui/button'
import { ROUTES } from '@/routes/navigation'

export function NotFoundPage() {
  return (
    <div className="bg-surface border-line shadow-card rounded-lg border">
      <EmptyState
        icon={Compass}
        title="Page not found"
        description="This route does not exist in the Phase 1 prototype. Use the navigation to return to a monitoring view."
        action={
          <Button asChild>
            <Link to={ROUTES.centerline}>Go to Digital Centerline</Link>
          </Button>
        }
      />
    </div>
  )
}
