/**
 * SSE 订阅「投票率」
 * ================
 * 依约定：投票期间只推送聚合投票率，不推送各候选人票数。
 * EventSource 自带断线重连，这里额外处理组件卸载时的关闭。
 */
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
      // EventSource 会自动重连；这里只更新状态供 UI 提示
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
