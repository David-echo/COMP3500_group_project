<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type Election } from '../api'

const route = useRoute()
const router = useRouter()
const electionId = Number(route.params.id)

const election = ref<Election | null>(null)
const rank = ref<number[]>([])
const error = ref('')
const submitting = ref(false)
const receipt = ref<{ code: string; auditSeq: number } | null>(null)
const copied = ref(false)

const position = computed(() => election.value?.positions[0])
const isIrv = computed(() => election.value?.tally_method === 'irv')

onMounted(async () => {
  try {
    const list = await api.elections()
    election.value = list.find((e) => e.id === electionId) ?? null
  } catch (e) {
    error.value = (e as Error).message
  }
})

function toggle(idx: number) {
  if (isIrv.value) {
    const at = rank.value.indexOf(idx)
    if (at >= 0) rank.value.splice(at, 1)
    else rank.value.push(idx)
  } else {
    rank.value = rank.value[0] === idx ? [] : [idx]
  }
}

const selectedNames = computed(() => {
  if (!position.value) return []
  return rank.value
    .map((i) => position.value!.candidates.find((c) => c.idx === i)?.name)
    .filter((n): n is string => Boolean(n))
})

const canSubmit = computed(() => rank.value.length > 0 && !submitting.value)

const notOpen = computed(
  () => election.value !== null && election.value.status !== 'open',
)

async function submit() {
  if (!election.value || !position.value) return
  error.value = ''
  submitting.value = true
  try {
    const r = await api.vote(election.value.id, position.value.id, rank.value)
    receipt.value = { code: r.receipt_code, auditSeq: r.audit_seq }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    submitting.value = false
  }
}

async function copyCode() {
  if (!receipt.value) return
  try {
    await navigator.clipboard.writeText(receipt.value.code)
    copied.value = true
    setTimeout(() => (copied.value = false), 1800)
  } catch {
    
  }
}
</script>

<template>
  <div class="container page ballot-page">
    
    <header class="page-head">
      <div>
        <button class="backlink" @click="router.push('/elections')">← Back to elections</button>
        <h1 class="page-title mt-3">{{ election?.title ?? 'Vote' }}</h1>
        <p v-if="position" class="page-sub">{{ position.title }}</p>
      </div>
      <span v-if="election" class="badge" :class="`badge-${election.status}`">
        {{ election.status_label }}
      </span>
    </header>

    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

    
    <section v-if="receipt" class="card receipt-card rise-in">
      <div class="card-body">
        <div class="receipt-head">
          <span class="receipt-icon" aria-hidden="true">✓</span>
          <div>
            <h2 class="card-title">Vote submitted</h2>
            <p class="page-sub">Save the receipt code below — it confirms that your ballot was counted.</p>
          </div>
        </div>

        <div class="receipt-code">
          <span class="mono">{{ receipt.code }}</span>
          <button class="btn btn-ghost btn-sm" @click="copyCode">
            {{ copied ? 'Copied' : 'Copy' }}
          </button>
        </div>

        <p class="hint">
          Audit entry #{{ receipt.auditSeq }} · The receipt does <strong>not</strong> contain
          your choice, so it cannot prove to anyone how you voted.
        </p>

        <div class="row mt-5">
          <button class="btn btn-ghost" @click="router.push('/receipt')">Verify receipt</button>
          <button class="btn" @click="router.push('/elections')">Back to elections</button>
        </div>
      </div>
    </section>

    
    <section v-else-if="notOpen" class="card">
      <div class="card-body">
        <div class="alert alert-info">
          This election is "{{ election?.status_label }}" and is not accepting votes.
        </div>
        <div class="row mt-4">
          <button class="btn btn-ghost" @click="router.push('/elections')">Back</button>
        </div>
      </div>
    </section>

    
    <section v-else-if="election && position" class="ballot-grid">
      <div class="card">
        <div class="card-head">
          <h2 class="card-title">Choose a candidate</h2>
          <span class="hint">
            {{ isIrv ? 'Click in order of preference' : 'Single choice — click to select' }}
          </span>
        </div>

        <ul class="candidate-list">
          <li
            v-for="c in position.candidates"
            :key="c.idx"
            class="candidate"
            :class="{ selected: rank.includes(c.idx) }"
            role="button"
            tabindex="0"
            :aria-pressed="rank.includes(c.idx)"
            @click="toggle(c.idx)"
            @keydown.enter.prevent="toggle(c.idx)"
            @keydown.space.prevent="toggle(c.idx)"
          >
            <span class="marker" :class="{ on: rank.includes(c.idx) }">
              {{ rank.includes(c.idx) ? rank.indexOf(c.idx) + 1 : '' }}
            </span>
            <span class="candidate-text">
              <strong>{{ c.name }}</strong>
              <small>{{ c.party || 'Independent' }}</small>
            </span>
            <span v-if="rank.includes(c.idx)" class="tick" aria-hidden="true">✓</span>
          </li>
        </ul>
      </div>

      
      <aside class="card summary">
        <div class="card-body">
          <h2 class="card-title">Confirm your vote</h2>

          <div class="summary-body">
            <p class="muted text-xs">Your selection</p>
            <ol v-if="selectedNames.length" class="summary-list">
              <li v-for="(n, i) in selectedNames" :key="i">
                <span v-if="rank.length > 1" class="idx">{{ i + 1 }}</span>
                {{ n }}
              </li>
            </ol>
            <p v-else class="empty-inline">No candidate selected</p>
          </div>

          <button class="btn btn-block" :disabled="!canSubmit" @click="submit">
            {{ submitting ? 'Submitting…' : 'Confirm vote' }}
          </button>

          <p class="hint mt-3">
            {{ isIrv
              ? 'Ranked choice: selecting one candidate is allowed.'
              : 'Single choice: only one candidate.' }}
            This cannot be changed after submission.
          </p>
        </div>
      </aside>
    </section>

    <div v-else class="card empty">Loading…</div>
  </div>
</template>

<style scoped>
.ballot-page {
  max-width: 980px;
}

.backlink {
  border: none;
  background: none;
  padding: 0;
  color: var(--muted);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
}
.backlink:hover {
  color: var(--brand);
}

.ballot-grid {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: var(--s-4);
  align-items: start;
}

.candidate-list {
  list-style: none;
  margin: 0;
  padding: var(--s-3);
  display: grid;
  gap: var(--s-2);
}

.candidate {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: var(--s-3) var(--s-4);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease);
}

.candidate:hover {
  border-color: var(--brand-line);
  background: #fbfdff;
}

.candidate.selected {
  border-color: var(--brand);
  background: var(--brand-soft);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.marker {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex: none;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--surface);
  color: var(--muted);
  font-size: var(--text-xs);
  font-weight: 700;
}

.marker.on {
  border-color: var(--brand);
  background: var(--brand);
  color: #fff;
}

.candidate-text {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
  min-width: 0;
}
.candidate-text strong {
  font-size: var(--text-base);
  font-weight: 600;
}
.candidate-text small {
  color: var(--muted);
  font-size: var(--text-xs);
}

.tick {
  margin-left: auto;
  color: var(--brand);
  font-weight: 700;
}


.summary {
  position: sticky;
  top: calc(var(--topbar-h) + var(--s-4));
}

.summary-body {
  margin: var(--s-4) 0 var(--s-5);
  min-height: 64px;
}

.summary-list {
  margin: var(--s-2) 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
  font-size: var(--text-sm);
}

.summary-list li {
  display: flex;
  align-items: center;
  gap: var(--s-2);
}

.idx {
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-dark);
  font-size: 11px;
  font-weight: 700;
  flex: none;
}

.empty-inline {
  color: var(--muted);
  font-size: var(--text-sm);
}


.receipt-card {
  max-width: 620px;
  margin: 0 auto;
}

.receipt-head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
}

.receipt-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex: none;
  border-radius: 50%;
  background: var(--ok-soft);
  border: 1px solid var(--ok-line);
  color: var(--ok);
  font-weight: 700;
}

.receipt-code {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
  margin: var(--s-5) 0 var(--s-3);
  padding: var(--s-4) var(--s-5);
  border: 1px dashed var(--brand-line);
  border-radius: var(--r-md);
  background: var(--brand-soft);
}

.receipt-code .mono {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: var(--brand-dark);
}

@media (max-width: 860px) {
  .ballot-grid {
    grid-template-columns: 1fr;
  }
  .summary {
    position: static;
  }
}
</style>
