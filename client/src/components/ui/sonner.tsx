import { Toaster as Sonner, type ToasterProps } from 'sonner'

function Toaster(props: ToasterProps) {
  return (
    <Sonner
      position="bottom-right"
      closeButton
      toastOptions={{
        classNames: {
          toast:
            'group !bg-surface !border-line !shadow-overlay !rounded-lg !border !text-ink !text-[13px] !font-sans',
          title: '!text-ink !font-semibold !text-[13px]',
          description: '!text-ink-soft !text-[12px]',
          actionButton: '!bg-brand !text-white !rounded-md !text-[12px]',
          cancelButton: '!bg-surface-muted !text-ink-soft !rounded-md !text-[12px]',
          closeButton: '!bg-surface !border-line !text-ink-soft',
          success: '[&_[data-icon]]:!text-normal',
          warning: '[&_[data-icon]]:!text-warning',
          error: '[&_[data-icon]]:!text-critical',
          info: '[&_[data-icon]]:!text-brand',
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
