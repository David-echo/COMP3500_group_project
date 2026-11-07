
import { onBeforeUnmount, ref } from 'vue'

export interface TurnoutEvent {
  election_id: number
  voted: number
  total: number
  percent: number
}

export function useTurnout() {
  const turnout = ref<TurnoutEvent | null>(null)
  const connected = ref(false)
  let es: EventSource | null = null

  function subscribe(electionId: number) {
    close()
    es = new EventSource(`/api/v1/events/turnout?election_id=${electionId}`)

    es.addEventListener('open', () => {
      connected.value = true
    })
    es.addEventListener('turnout', (ev: MessageEvent) => {
      turnout.value = JSON.parse(ev.data) as TurnoutEvent
    })
    es.addEventListener('error', () => {
      connected.value = false
    })
  }

  function close() {
    es?.close()
    es = null
    connected.value = false
  }

  onBeforeUnmount(close)

  return { turnout, connected, subscribe, close }
}
