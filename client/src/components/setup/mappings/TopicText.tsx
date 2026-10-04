import { Fragment } from 'react'

/** A topic that wraps only after its slashes; copying it still gives the exact text. */
export function TopicText({ topic }: { topic: string }) {
  const parts = topic.split('/')
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 && (
            <>
              /<wbr />
            </>
          )}
        </Fragment>
      ))}
    </>
  )
}
