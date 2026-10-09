import type { RequestStatus } from '@/types/workflowApi'

/**
 * The reason assistant's own words, in Tagalog (the operators' default, LAN-01) and English (ADR-0043). Technical words
 * stay in English, the way operators say them: setpoint, target, seal, OCAP, Manager. The OCAP's text and the record
 * stay as written.
 */
export type Lang = 'fil' | 'en'

export const LANG_LABEL: Record<Lang, string> = { fil: 'Tagalog', en: 'English' }

export interface AssistantText {
  language: string
  nothingWaiting: string
  idle: string
  mismatchOn: (zone: string) => string
  setpointIs: (parameter: string) => string
  againstTarget: (target: string, way: 'raised' | 'lowered' | null, since: string) => string
  lookingAtOcap: (zone: string) => string
  whyChanged: string
  askedByAi: string
  otherTypeIt: string
  englishOrFilipino: string
  pickAbove: string
  typeReason: string
  addNote: string
  yourAnswer: string
  send: string
  readingOcap: string
  aiSummary: string
  summarising: string
  summaryNote: string
  fromOcap: (where: string) => string
  thisApplies: (citation: string) => string
  noneApply: string
  readIt: string
  guidanceFrom: (by: string) => string
  ocapPicked: string
  ocapMatches: (n: number) => string
  readInFull: string
  thisOneApplies: string
  readFirst: string
  askManager: (one: boolean) => string
  ackSection: string
  ackGuidance: string
  reviewOnly: string
  waitingManager: string
  closed: Partial<Record<RequestStatus, string>>
  closedOther: string
  next: (zone: string) => string
  close: string
  minimise: string
  previousMismatch: string
  nextMismatch: string
  of: (a: number, b: number) => string
  bubbleReasons: (n: number) => string
  bubbleManager: string
}

export const TEXT: Record<Lang, AssistantText> = {
  fil: {
    language: 'Wika',
    nothingWaiting: 'Walang naghihintay',
    idle: 'Wala kang kailangang sagutin. Kusa akong lalabas kapag may setpoint na kailangan ng dahilan.',
    mismatchOn: (zone) => `HMI mismatch sa ${zone}`,
    setpointIs: (parameter) => `Ang setpoint ng ${parameter} ay `,
    againstTarget: (target, way, since) =>
      `, pero ang target ay ${target}${way ? ` (${way === 'raised' ? 'itinaas' : 'ibinaba'})` : ''}, mula ${since}.`,
    lookingAtOcap: (zone) => `Tinitingnan ang OCAP para sa ${zone}…`,
    whyChanged: 'Bakit mo ito binago?',
    askedByAi: 'Tanong ng AI, mula sa OCAP',
    otherTypeIt: 'Iba pa: ita-type ko',
    englishOrFilipino: 'English o Filipino',
    pickAbove: 'Pumili ng dahilan sa itaas',
    typeReason: 'I-type ang dahilan mo',
    addNote: 'Magdagdag ng note (opsyonal), saka i-send',
    yourAnswer: 'Ang sagot mo',
    send: 'I-send',
    readingOcap: 'Binabasa ang OCAP para sa susunod na tanong…',
    aiSummary: 'Buod ng AI mula sa OCAP',
    summarising: 'Binubuod ng AI ang OCAP…',
    summaryNote: 'Basahin pa rin ang OCAP sa ibaba bago pumili.',
    fromOcap: (where) => `Mula sa ${where}`,
    thisApplies: (citation) => `Ito ang tugma: ${citation}`,
    noneApply: 'Walang tugma',
    readIt: 'Nabasa ko na',
    guidanceFrom: (by) => `Gabay mula kay ${by}`,
    ocapPicked: 'Ito ang sinasabi ng OCAP para sa dahilan mo. Basahin ito, saka sabihin kung tugma ito.',
    ocapMatches: (n) =>
      n === 1
        ? 'Tugma ang bahaging ito ng OCAP sa isinulat mo. Basahin ito, saka piliin.'
        : `Tugma ang ${n} bahaging ito ng OCAP sa isinulat mo. Basahin ang angkop, saka piliin ito.`,
    readInFull: 'Basahin nang buo',
    thisOneApplies: 'Ito ang tugma',
    readFirst: 'Basahin muna nang buo',
    askManager: (one) => (one ? 'Hindi tugma: magtanong sa Manager' : 'Walang tugma: magtanong sa Manager'),
    ackSection: 'Basahin ang napiling bahagi ng OCAP, saka kumpirmahin.',
    ackGuidance: 'Basahin ang gabay ng Manager sa itaas, saka kumpirmahin.',
    reviewOnly: 'Itinatala lang nito na nabasa mo ito, hindi na nagawa ang bawat hakbang.',
    waitingManager: 'Walang tugmang OCAP, kaya hiningan ng gabay ang isang Manager. Babalik ako rito pagdating ng gabay.',
    closed: {
      done: 'Naitala na. Salamat!',
      resolved: 'Bumalik na sa target ang HMI setpoint: wala nang kailangang gawin dito.',
      superseded: 'Nagbago ulit ang setpoint, kaya may bagong tanong na papalit dito.',
      not_answered: 'Natapos ang shift bago ito nasagot.',
      cancelled: 'Nagsara ang alarm: pinatay ang zone.',
    },
    closedOther: 'Sarado na ito.',
    next: (zone) => `Susunod: ${zone}`,
    close: 'Isara',
    minimise: 'Paliitin',
    previousMismatch: 'Nakaraang mismatch',
    nextMismatch: 'Susunod na mismatch',
    of: (a, b) => `${a} sa ${b}`,
    bubbleReasons: (n) => `May ${n} dahilang hinihintay`,
    bubbleManager: 'Hinihintay ang Manager',
  },
  en: {
    language: 'Language',
    nothingWaiting: 'Nothing waiting',
    idle: 'Nothing is waiting for you. I’ll open by myself when a setpoint needs a reason.',
    mismatchOn: (zone) => `HMI mismatch on ${zone}`,
    setpointIs: (parameter) => `The ${parameter} setpoint is `,
    againstTarget: (target, way, since) => ` against its target ${target}${way ? ` (${way})` : ''}, since ${since}.`,
    lookingAtOcap: (zone) => `Looking at the OCAP for ${zone}…`,
    whyChanged: 'Why did you change it?',
    askedByAi: 'Asked by the AI, from the OCAP',
    otherTypeIt: 'Other: I’ll type it',
    englishOrFilipino: 'English or Filipino',
    pickAbove: 'Pick a reason above',
    typeReason: 'Type your reason',
    addNote: 'Add a note (optional), then send',
    yourAnswer: 'Your answer',
    send: 'Send',
    readingOcap: 'Reading the OCAP for your next questions…',
    aiSummary: 'AI summary of the OCAP',
    summarising: 'The AI is summing up the OCAP…',
    summaryNote: 'Still read the OCAP below before you choose.',
    fromOcap: (where) => `From ${where}`,
    thisApplies: (citation) => `This one applies: ${citation}`,
    noneApply: 'None of these apply',
    readIt: 'I’ve read it',
    guidanceFrom: (by) => `Guidance from ${by}`,
    ocapPicked: 'Here is what the OCAP says for your reason. Read it, then tell me if it applies.',
    ocapMatches: (n) =>
      n === 1
        ? 'This OCAP section matches what you wrote. Read it, then choose it.'
        : `These ${n} OCAP sections match what you wrote. Read the one that fits, then choose it.`,
    readInFull: 'Read in full',
    thisOneApplies: 'This one applies',
    readFirst: 'Read it in full first',
    askManager: (one) => (one ? 'It doesn’t apply: ask a Manager' : 'None of these apply: ask a Manager'),
    ackSection: 'Read the OCAP section you chose, then confirm.',
    ackGuidance: 'Read the Manager’s guidance above, then confirm.',
    reviewOnly: 'This records that you reviewed it, not that each step was done.',
    waitingManager: 'None of the OCAPs fit, so a Manager has been asked to guide you. I’ll come back here when the guidance arrives.',
    closed: {
      done: 'Recorded. Thank you!',
      resolved: 'The HMI setpoint is back on its target: nothing more to do here.',
      superseded: 'The setpoint changed again, so a new question replaces this one.',
      not_answered: 'The shift ended before this was finished.',
      cancelled: 'The alarm closed: the zone was switched off.',
    },
    closedOther: 'This one is closed.',
    next: (zone) => `Next: ${zone}`,
    close: 'Close',
    minimise: 'Minimise',
    previousMismatch: 'Previous mismatch',
    nextMismatch: 'Next mismatch',
    of: (a, b) => `${a} of ${b}`,
    bubbleReasons: (n) => `${n} reason${n === 1 ? '' : 's'} to give`,
    bubbleManager: 'Waiting for a Manager',
  },
}

/** The fixed questions as they come out of the box, in Tagalog; one an Administrator writes shows as written */
const FIXED_FIL: Record<string, string> = {
  'Why did you change it?': 'Bakit mo ito binago?',
  'What was changed, and why?': 'Ano ang binago mo, at bakit?',
  'Is the product affected?': 'Apektado ba ang produkto?',
}

/** A question in the chosen language: the AI's Filipino when it wrote one that passed, a fixed one's own, else the English */
export function spoken(q: { question: string; questionFil?: string | null; by: 'ai' | 'fixed' }, lang: Lang): string {
  if (lang !== 'fil') return q.question
  return q.questionFil ?? (q.by === 'fixed' ? FIXED_FIL[q.question] : undefined) ?? q.question
}
