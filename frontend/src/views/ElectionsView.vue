<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
    const firstOpen = elections.value.find((e) => e.status === 'open')
    if (firstOpen) watch(firstOpen.id)
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

function votedCount(e: Election) {
  if (watching.value === e.id && turnout.value) return turnout.value.voted
  return e.turnout.voted
}

function goVote(e: Election) {
  close()
  router.push(`/elections/${e.id}/vote`)
}

const canVote = (e: Election) =>
  e.status === 'open' && e.my_vote_status === 'NOT_VOTED'

const statusClass = (s: Election['status']) => `badge-${s}`

const openCount = computed(() => elections.value.filter(canVote).length)

onMounted(load)
</script>

<template>
  <div class="container page">
    <header class="page-head">
      <div>
        <h1 class="page-title">Elections</h1>
        <p class="page-sub">
          {{ elections.length }} elections
          <template v-if="openCount > 0">· {{ openCount }} awaiting your vote</template>
        </p>
      </div>
      <span class="live" :class="{ on: connected }">
        <span class="live-dot" aria-hidden="true"></span>
        {{ connected ? 'Live updates on' : 'Live updates offline' }}
      </span>
    </header>

    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

    <div v-if="!elections.length && !error" class="card empty">No elections yet</div>

    <ul class="election-list">
      <li
        v-for="e in elections"
        :key="e.id"
        class="election"
        :class="{ actionable: canVote(e) }"
        @mouseenter="e.status === 'open' && watch(e.id)"
      >
        <div class="election-main">
          <div class="election-title-row">
            <h2 class="election-title">{{ e.title }}</h2>
            <span class="badge" :class="statusClass(e.status)">{{ e.status_label }}</span>
            <span v-if="e.my_vote_status === 'VOTED'" class="badge badge-open">Voted</span>
          </div>

          <p class="election-meta">
            <span>{{ e.tally_method === 'irv' ? 'Ranked choice' : 'First past the post' }}</span>
            <span class="sep" aria-hidden="true">·</span>
            <span>{{ e.positions.reduce((n, p) => n + p.candidates.length, 0) }} candidates</span>
            <template v-if="e.closes_at">
              <span class="sep" aria-hidden="true">·</span>
              <span>Closes {{ e.closes_at.replace('T', ' ').slice(0, 16) }}</span>
            </template>
          </p>

          <div class="turnout">
            <div class="turnout-head">
              <span class="muted text-xs">Turnout</span>
              <span class="num text-sm">
                <strong>{{ percent(e) }}%</strong>
                <span class="muted">
                  （{{ votedCount(e) }}/{{ e.turnout.total }}）
                </span>
              </span>
            </div>
            <div class="progress">
              <span :style="{ width: percent(e) + '%' }"></span>
            </div>
          </div>
        </div>

        <div class="election-action">
          <button
            v-if="canVote(e)"
            class="btn"
            @click="goVote(e)"
          >
            Vote now
          </button>
          <button
            v-else-if="e.status === 'closed' || e.status === 'published'"
            class="btn btn-ghost"
            @click="goVote(e)"
          >
            View results
          </button>
          <span v-else-if="e.my_vote_status === 'VOTED'" class="muted text-sm done">
            Completed
          </span>
          
          <span v-else-if="e.status === 'open'" class="muted text-sm done">Voters only</span>
          <span v-else class="muted text-sm done">Not open yet</span>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-pill);
  background: var(--surface);
  color: var(--muted);
  font-size: var(--text-xs);
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}

.live.on {
  border-color: var(--ok-line);
  background: var(--ok-soft);
  color: #047857;
}
.live.on .live-dot {
  background: var(--ok);
}

.election-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--s-3);
}

.election {
  display: flex;
  align-items: center;
  gap: var(--s-5);
  padding: var(--s-4) var(--s-5);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-xs);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease),
    transform var(--dur-fast) var(--ease);
}

.election.actionable:hover {
  border-color: var(--brand-line);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.election-main {
  flex: 1 1 auto;
  min-width: 0;
}

.election-title-row {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  flex-wrap: wrap;
}

.election-title {
  font-size: var(--text-md);
  font-weight: 620;
  letter-spacing: -0.01em;
}

.election-meta {
  margin-top: 6px;
  color: var(--muted);
  font-size: var(--text-sm);
}

.sep {
  margin: 0 6px;
  color: #cbd5e1;
}

.turnout {
  margin-top: var(--s-3);
  max-width: 340px;
}

.turnout-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--s-3);
  margin-bottom: 6px;
}

.election-action {
  flex: none;
  min-width: 96px;
  display: flex;
  justify-content: flex-end;
}

.done {
  padding-right: var(--s-2);
}

@media (max-width: 720px) {
  .election {
    flex-direction: column;
    align-items: stretch;
    gap: var(--s-3);
  }
  .election-action {
    justify-content: flex-start;
  }
  .turnout {
    max-width: none;
  }
}
</style>
