<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Election } from '../api'
import { useTurnout } from '../composables/useTurnout'

const elections = ref<Election[]>([])
const error = ref('')
const router = useRouter()
const { turnout, connected, subscribe, close } = useTurnout()
const watching = ref<number | null>(null)

async function load() {
  try {
    elections.value = await api.elections()
  } catch (e) {
    error.value = (e as Error).message
  }
}

function watch(id: number) {
  watching.value = id
  subscribe(id)
}

function percent(e: Election) {
  if (watching.value === e.id && turnout.value) return turnout.value.percent
  return e.turnout.percent
}

function goVote(e: Election) {
  close()
  router.push(`/elections/${e.id}/vote`)
}

onMounted(load)
</script>

<template>
  <div v-if="error" class="alert a-bad">{{ error }}</div>

  <div class="card">
    <h2>🗂️ 请选择要参与的选举</h2>
    <div class="mut" style="margin-bottom: 12px">
      投票流程：登录 → <b>选择选举</b> → 选择候选人 → 确认投票 → 拿到凭证码
    </div>

    <div
      v-for="e in elections"
      :key="e.id"
      class="ecard"
      :class="{ pick: e.status === 'open' && e.my_vote_status === 'NOT_VOTED' }"
      @mouseenter="e.status === 'open' && watch(e.id)"
    >
      <div>
        <div class="ttl">{{ e.title }}</div>
        <div class="mut">
          {{ e.tally_method === 'irv' ? '排序复选制' : '单选制' }} ·
          {{ e.positions.reduce((n, p) => n + p.candidates.length, 0) }} 名候选 ·
          投票率 {{ percent(e) }}%（{{ e.turnout.voted }}/{{ e.turnout.total }}）
          <span v-if="watching === e.id && connected" style="color: #0f9d58">· 实时</span>
        </div>
      </div>
      <div class="row">
        <span class="badge" :class="`b-${e.status}`">{{ e.status_label }}</span>
        <span
          v-if="e.my_vote_status === 'VOTED'"
          class="badge b-open"
        >✔ 您已投票</span>
        <button
          v-if="e.status === 'open' && e.my_vote_status === 'NOT_VOTED'"
          class="btn sm"
          @click="goVote(e)"
        >去投票 →</button>
        <button
          v-else-if="e.status === 'closed' || e.status === 'published'"
          class="btn sm ghost"
          @click="goVote(e)"
        >查看结果</button>
      </div>
    </div>

    <div v-if="!elections.length" class="mut">暂无选举</div>
  </div>
</template>

<style scoped>
.ecard {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  border: 1px solid var(--line); border-radius: 11px; padding: 14px 16px;
  margin-bottom: 10px; background: #fbfcfe; flex-wrap: wrap;
}
.ecard.pick { cursor: pointer; }
.ecard.pick:hover { border-color: var(--brand); background: #f4f8ff; }
.ttl { font-weight: 650; font-size: 14.5px; }
</style>
