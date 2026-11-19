import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)) }

const buttonVariants = cva(
  'ui-button inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-4 disabled:pointer-events-none disabled:opacity-45',
  {
    variants: {
      variant: {
        default: 'ui-primary',
        outline: 'ui-outline',
        ghost: 'ui-ghost',
      },
      size: { default: 'h-11 px-5', sm: 'h-9 px-3', icon: 'h-10 w-10' },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

type Props = React.ComponentPropsWithRef<'button'> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }

export function Button({ className, variant, size, asChild = false, ...props }: Props) {
  const Component = asChild ? Slot : 'button'
  return <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
