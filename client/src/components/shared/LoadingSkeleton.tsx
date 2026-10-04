import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/utils/cn'

export function CardGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: count }, (_, index) => (
        <Card key={index} className="gap-0 py-4 pr-4 pl-5">
          <div className="flex items-start justify-between">
            <Skeleton className="h-2.5 w-20" />
            <Skeleton className="size-7 rounded-md" />
          </div>
          <Skeleton className="mt-3 h-6 w-12" />
          <Skeleton className="mt-2.5 h-2.5 w-full" />
        </Card>
      ))}
    </div>
  )
}

export function TableSkeleton({
  rows = 8,
  columns = 7,
}: {
  rows?: number
  columns?: number
}) {
  return (
    <div className="overflow-hidden">
      <div className="bg-surface-muted border-line flex h-10 items-center gap-4 border-b px-3">
        {Array.from({ length: columns }, (_, index) => (
          <Skeleton key={index} className="h-2.5 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, rowIndex) => (
        <div
          key={rowIndex}
          className="border-line-soft flex h-11 items-center gap-4 border-b px-3"
        >
          {Array.from({ length: columns }, (_, columnIndex) => (
            <Skeleton
              key={columnIndex}
              className={cn('h-3 flex-1', columnIndex === 0 && 'max-w-20')}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

export function ChartSkeleton({ height = 320 }: { height?: number }) {
  return (
    <div className="flex flex-col gap-3 p-5" style={{ height }}>
      <div className="flex gap-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-3 w-20" />
      </div>
      <Skeleton className="flex-1 rounded-md" />
    </div>
  )
}

export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: rows }, (_, index) => (
        <Card key={index} className="gap-0 p-4">
          <div className="flex items-start gap-3">
            <Skeleton className="size-8 shrink-0 rounded-md" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-3 w-1/3" />
              <Skeleton className="h-2.5 w-2/3" />
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}
