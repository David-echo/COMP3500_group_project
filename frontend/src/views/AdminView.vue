<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { api, type Election, type ResultRow } from '../api'

const elections = ref<Election[]>([])
const error = ref('')
const results = ref<ResultRow[] | null>(null)
const resultsMsg = ref('')
const integrity = ref<{
  all_passed: boolean
  checks: Array<{ name: string; passed: boolean; detail: string }>
} | null>(null)
const audit = ref<{
  ok: boolean
  length: number
  first_bad_seq: number | null
  message: string
} | null>(null)
const chartEl = ref<HTMLDivElement | null>(null)
const currentElection = ref<Election | null>(null)
let chart: echarts.ECharts | null = null

const stats = computed(() => ({
  total: elections.value.length,
  open: elections.value.filter((e) => e.status === 'open').length,
  published: elections.value.filter((e) => e.status === 'published').length,
}))

async function load() {
  try {
    elections.value = await api.elections()
  } catch (e) {
    error.value = (e as Error).message
  }
}

async function setStatus(e: Election, status: string) {
  error.value = ''
  try {
    await api.setStatus(e.id, status)
    await load()
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function publish(e: Election) {
  error.value = ''
  try {
    await api.publish(e.id)
    await load()
    await showResults(e)
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function showResults(e: Election) {
  try {
    currentElection.value = e
    const r = await api.results(e.id)
    resultsMsg.value = r.published ? '' : r.message
    results.value = r.published ? r.results : null
    if (r.published) {
      await nextTick()
      renderChart()
    } else if (chart) {
      chart.clear()
    }
  } catch (err) {
    error.value = (err as Error).message
  }
}

function renderChart() {
  if (!chartEl.value || !results.value?.length) return
  if (!chart) chart = echarts.init(chartEl.value)

  const row = results.value[0]
  const entries = Object.entries(row.counts).sort((a, b) => Number(a[0]) - Number(b[0]))

  const position = currentElection.value?.positions.find(
    (p) => p.id === row.position_id,
  )
  const nameOf = (idx: number) =>
    position?.candidates.find((c) => c.idx === idx)?.name ?? `Candidate ${idx}`

  const data = entries.map(([k, v]) => ({
    idx: Number(k),
    name: nameOf(Number(k)),
    value: v,
    isWinner: row.winner_idx === Number(k),
  }))

  chart.setOption(
    {
      grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: {
        type: 'category',
        data: data.map((d) => d.name),
        axisLine: { lineStyle: { color: '#e2e8f0' } },
        axisTick: { show: false },
        axisLabel: {
          color: '#64748b',
          fontSize: 12,
          interval: 0,
          width: 120,
          overflow: 'break',
        },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: '#eef2f7' } },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
      },
      series: [
        {
          type: 'bar',
          data: data.map((d) => ({
            value: d.value,
            itemStyle: {
              color: d.isWinner ? '#78c03c' : '#0078c0',
              borderRadius: [4, 4, 0, 0],
            },
          })),
          barMaxWidth: 48,
          label: { show: true, position: 'top', color: '#475569', fontSize: 12 },
        },
      ],
    },
    true,
  )
  chart.resize()
}

async function checkIntegrity(e: Election) {
  try {
    integrity.value = await api.integrity(e.id)
  } catch (err) {
    error.value = (err as Error).message
  }
}

async function verifyAudit() {
  try {
    audit.value = await api.auditVerify()
  } catch (e) {
    error.value = (e as Error).message
  }
}

onMounted(async () => {
  await load()
  await verifyAudit()
})
</script>

<template>
  <div class="container page">
    <header class="page-head">
      <div>
        <h1 class="page-title">Admin console</h1>
        <p class="page-sub">Lifecycle control, tallying, integrity checks and the audit chain</p>
      </div>
      <button class="btn btn-ghost btn-sm" @click="load">Refresh</button>
    </header>

    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

    
    <div class="stat-grid">
      <div class="stat">
        <span class="stat-label">Elections</span>
        <strong class="stat-value num">{{ stats.total }}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">Open</span>
        <strong class="stat-value num">{{ stats.open }}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">Published</span>
        <strong class="stat-value num">{{ stats.published }}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">Audit entries</span>
        <strong class="stat-value num">{{ audit?.length ?? '—' }}</strong>
      </div>
    </div>

    
    <section class="card mt-4">
      <div class="card-head">
        <h2 class="card-title">Elections</h2>
        <span class="hint">Status moves one way: Scheduled → Voting open → Closed → Published</span>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Election</th>
              <th>Status</th>
              <th>Turnout</th>
              <th style="text-align: right">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in elections" :key="e.id">
              <td>
                <div class="cell-title">{{ e.title }}</div>
                <div class="hint">
                  {{ e.tally_method === 'irv' ? 'Ranked choice' : 'First past the post' }}
                </div>
              </td>
              <td>
                <span class="badge" :class="`badge-${e.status}`">{{ e.status_label }}</span>
              </td>
              <td class="num">{{ e.turnout.percent }}%</td>
              <td>
                <div class="row" style="justify-content: flex-end">
                  <button
                    v-if="e.status === 'scheduled'"
                    class="btn btn-ghost btn-sm"
                    @click="setStatus(e, 'open')"
                  >
                    Open voting
                  </button>
                  <button
                    v-if="e.status === 'open'"
                    class="btn btn-ghost btn-sm"
                    @click="setStatus(e, 'closed')"
                  >
                    Close
                  </button>
                  <button
                    v-if="e.status === 'closed'"
                    class="btn btn-sm"
                    @click="publish(e)"
                  >
                    Tally &amp; publish
                  </button>
                  <button
                    v-if="e.status !== 'scheduled'"
                    class="btn btn-ghost btn-sm"
                    @click="showResults(e)"
                  >
                    View results
                  </button>
                  <button class="btn btn-quiet btn-sm" @click="checkIntegrity(e)">
                    Integrity
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    
    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Results</h2>
        <span v-if="results?.length" class="row">
          <span class="badge badge-published">{{ results[0].tally_label }}</span>
          <span class="hint">Valid ballots: {{ results[0].ballot_count }}</span>
        </span>
      </div>

      <div class="card-body">
        <div v-if="resultsMsg" class="alert alert-info">{{ resultsMsg }}</div>

        <template v-if="results?.length">
          <div class="winner-row">
            <div>
              <p class="hint">Winner</p>
              <p class="winner-name">
                {{ results[0].winner_name ?? 'No single winner (tie)' }}
              </p>
            </div>
            <div class="digest">
              <p class="hint">Result digest (SHA-256)</p>
              <p class="mono text-xs">{{ results[0].digest }}</p>
            </div>
          </div>
          <div ref="chartEl" class="chart"></div>
        </template>

        <p v-else class="hint">
          Select a closed election and choose Tally &amp; publish or View results.
        </p>
      </div>
    </section>

    
    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Integrity checks</h2>
        <span v-if="integrity" class="badge" :class="integrity.all_passed ? 'badge-open' : 'badge-closed'">
          {{ integrity.all_passed ? 'All checks passed' : 'Inconsistencies found' }}
        </span>
      </div>
      <div class="card-body">
        <ul v-if="integrity" class="check-list">
          <li v-for="c in integrity.checks" :key="c.name" class="check">
            <span class="check-icon" :class="c.passed ? 'ok' : 'bad'" aria-hidden="true">
              {{ c.passed ? '✓' : '✕' }}
            </span>
            <span class="check-text">
              <strong>{{ c.name }}</strong>
              <small>{{ c.detail }}</small>
            </span>
          </li>
        </ul>
        <p v-else class="hint">Use the Integrity button for an election to run the checks.</p>
      </div>
    </section>

    
    <section class="card">
      <div class="card-head">
        <h2 class="card-title">Audit chain</h2>
        <button class="btn btn-ghost btn-sm" @click="verifyAudit">Re-verify</button>
      </div>
      <div class="card-body">
        <div v-if="audit">
          <div class="alert" :class="audit.ok ? 'alert-ok' : 'alert-danger'">
            {{ audit.ok ? '✓' : '✕' }} {{ audit.message }}
          </div>
          <p class="hint mt-3">
            {{ audit.length }} entries<template v-if="audit.first_bad_seq">
              , first break at #{{ audit.first_bad_seq }}</template
            >. The hash chain can only <strong>detect</strong> tampering; it cannot stop an
            attacker who recomputes the whole chain.
          </p>
        </div>
        <p v-else class="hint">Verifying…</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s-3);
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s-4) var(--s-5);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-xs);
}

.stat-label {
  font-size: var(--text-xs);
  color: var(--muted);
}

.stat-value {
  font-size: var(--text-xl);
  font-weight: 680;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.table-wrap {
  overflow-x: auto;
}

.cell-title {
  font-weight: 600;
  color: var(--ink);
}

.winner-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-5);
  flex-wrap: wrap;
}

.winner-name {
  font-size: var(--text-md);
  font-weight: 650;
  color: var(--ok);
}

.digest {
  min-width: 0;
  max-width: 420px;
}

.digest .mono {
  word-break: break-all;
  line-height: 1.7;
  color: var(--ink-soft);
}

.chart {
  height: 260px;
  margin-top: var(--s-4);
}

.check-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--s-3);
}

.check {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
}

.check-icon {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex: none;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 700;
}

.check-icon.ok {
  background: var(--ok-soft);
  border: 1px solid var(--ok-line);
  color: var(--ok);
}

.check-icon.bad {
  background: var(--danger-soft);
  border: 1px solid var(--danger-line);
  color: var(--danger);
}

.check-text {
  display: flex;
  flex-direction: column;
  line-height: 1.5;
}

.check-text strong {
  font-size: var(--text-sm);
  font-weight: 600;
}

.check-text small {
  color: var(--muted);
  font-size: var(--text-xs);
}
</style>
