<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type Election, type ResultRow } from '../api'

const route = useRoute()
const router = useRouter()
const electionId = Number(route.params.id)

const election = ref<Election | null>(null)
const results = ref<ResultRow[] | null>(null)
const message = ref('')
const title = ref('Results')
const error = ref('')
const loading = ref(true)

onMounted(async () => {
  try {
    const list = await api.elections()
    const e = list.find((x) => x.id === electionId) ?? null
    election.value = e
    if (e) title.value = e.title
    const r = await api.results(electionId)
    message.value = r.published ? '' : r.message
    results.value = r.published ? r.results : null
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})

function countEntries(row: ResultRow) {
  return Object.entries(row.counts)
    .map(([k, v]) => ({ idx: Number(k), votes: v }))
    .sort((a, b) => b.votes - a.votes)
}

function nameOf(row: ResultRow, idx: number) {
  const pos = election.value?.positions.find((p) => p.id === row.position_id)
  const found = pos?.candidates.find((c) => c.idx === idx)?.name
  if (found) return found
  if (row.winner_idx === idx && row.winner_name) return row.winner_name
  return `Candidate ${idx}`
}
</script>

<template>
  <div class="container page results-page">
    <header class="page-head">
      <div>
        <button class="backlink" @click="router.push('/elections')">← Back to elections</button>
        <h1 class="page-title mt-3">{{ title }}</h1>
        <p class="page-sub">Published results</p>
      </div>
    </header>

    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>
    <div v-else-if="loading" class="card empty">Loading…</div>
    <div v-else-if="message" class="card">
      <div class="card-body">
        <div class="alert alert-info">{{ message }}</div>
        <button class="btn btn-ghost mt-4" @click="router.push('/elections')">Back</button>
      </div>
    </div>

    <section v-else-if="results?.length" class="stack">
      <article v-for="row in results" :key="row.position_id" class="card">
        <div class="card-head">
          <h2 class="card-title">{{ row.position_title }}</h2>
          <span class="badge badge-published">{{ row.tally_label }}</span>
        </div>
        <div class="card-body">
          <p class="hint">Valid ballots: {{ row.ballot_count }}</p>
          <p class="winner">
            Winner:
            <strong>{{ row.winner_name ?? 'No single winner (tie)' }}</strong>
          </p>
          <ul class="counts">
            <li v-for="c in countEntries(row)" :key="c.idx">
              <span>{{ nameOf(row, c.idx) }}</span>
              <span class="num">{{ c.votes }}</span>
            </li>
          </ul>
          <p class="hint mono text-xs mt-3">Digest: {{ row.digest }}</p>
        </div>
      </article>
    </section>
    <div v-else class="card empty">No results available.</div>
  </div>
</template>

<style scoped>
.results-page { max-width: 720px; }
.backlink {
  border: none; background: none; padding: 0;
  color: var(--muted); font: inherit; font-size: var(--text-sm); cursor: pointer;
}
.backlink:hover { color: var(--brand); }
.stack { display: grid; gap: var(--s-3); }
.winner { margin: var(--s-3) 0; font-size: var(--text-md); }
.counts {
  list-style: none; margin: var(--s-3) 0 0; padding: 0;
  display: grid; gap: 8px;
}
.counts li {
  display: flex; justify-content: space-between; gap: var(--s-3);
  padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--r-md);
  background: var(--surface);
}
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
</style>
