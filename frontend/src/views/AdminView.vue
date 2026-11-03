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
  const data = entries.map(([k, v]) => ({
    idx: Number(k),
    name: `候选 ${k}`,
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
        axisLabel: { color: '#64748b', fontSize: 12 },
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
        <h1 class="page-title">管理台</h1>
        <p class="page-sub">状态控制、计票公示、完整性校验与审计链</p>
      </div>
      <button class="btn btn-ghost btn-sm" @click="load">刷新</button>
    </header>

    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

    <!-- 概览 -->
    <div class="stat-grid">
      <div class="stat">
        <span class="stat-label">选举总数</span>
        <strong class="stat-value num">{{ stats.total }}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">进行中</span>
        <strong class="stat-value num">{{ stats.open }}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">已公布</span>
        <strong class="stat-value num">{{ stats.published }}</strong>
      </div>
      <div class="stat">
        <span class="stat-label">审计记录</span>
        <strong class="stat-value num">{{ audit?.length ?? '—' }}</strong>
      </div>
    </div>

    <!-- 选举管理 -->
    <section class="card mt-4">
      <div class="card-head">
        <h2 class="card-title">选举管理</h2>
        <span class="hint">状态只能沿 未开始 → 进行中 → 已截止 → 已公布 单向推进</span>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>选举</th>
              <th>状态</th>
              <th>投票率</th>
              <th style="text-align: right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in elections" :key="e.id">
              <td>
                <div class="cell-title">{{ e.title }}</div>
                <div class="hint">
                  {{ e.tally_method === 'irv' ? '排序复选制' : '单选制' }}
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
                    开放投票
                  </button>
                  <button
                    v-if="e.status === 'open'"
                    class="btn btn-ghost btn-sm"
                    @click="setStatus(e, 'closed')"
                  >
                    截止
                  </button>
                  <button
                    v-if="e.status === 'closed'"
                    class="btn btn-sm"
                    @click="publish(e)"
                  >
                    计票公示
                  </button>
                  <button
                    v-if="e.status !== 'scheduled'"
                    class="btn btn-ghost btn-sm"
                    @click="showResults(e)"
                  >
                    查看结果
                  </button>
                  <button class="btn btn-quiet btn-sm" @click="checkIntegrity(e)">
                    完整性
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 计票结果 -->
    <section class="card">
      <div class="card-head">
        <h2 class="card-title">计票结果</h2>
        <span v-if="results?.length" class="row">
          <span class="badge badge-published">{{ results[0].tally_label }}</span>
          <span class="hint">有效票 {{ results[0].ballot_count }}</span>
        </span>
      </div>

      <div class="card-body">
        <div v-if="resultsMsg" class="alert alert-info">{{ resultsMsg }}</div>

        <template v-if="results?.length">
          <div class="winner-row">
            <div>
              <p class="hint">当选</p>
              <p class="winner-name">
                {{ results[0].winner_name ?? '无单一最高票（并列）' }}
              </p>
            </div>
            <div class="digest">
              <p class="hint">结果摘要 SHA-256</p>
              <p class="mono text-xs">{{ results[0].digest }}</p>
            </div>
          </div>
          <div ref="chartEl" class="chart"></div>
        </template>

        <p v-else class="hint">
          选择一场已截止的选举，点击「计票公示」或「查看结果」。
        </p>
      </div>
    </section>

    <!-- 完整性 -->
    <section class="card">
      <div class="card-head">
        <h2 class="card-title">完整性校验</h2>
        <span v-if="integrity" class="badge" :class="integrity.all_passed ? 'badge-open' : 'badge-closed'">
          {{ integrity.all_passed ? '全部通过' : '存在不一致' }}
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
        <p v-else class="hint">在选举列表中点击「完整性」运行校验。</p>
      </div>
    </section>

    <!-- 审计链 -->
    <section class="card">
      <div class="card-head">
        <h2 class="card-title">审计链</h2>
        <button class="btn btn-ghost btn-sm" @click="verifyAudit">重新校验</button>
      </div>
      <div class="card-body">
        <div v-if="audit">
          <div class="alert" :class="audit.ok ? 'alert-ok' : 'alert-danger'">
            {{ audit.ok ? '✓' : '✕' }} {{ audit.message }}
          </div>
          <p class="hint mt-3">
            共 {{ audit.length }} 条记录<template v-if="audit.first_bad_seq">
              ，首条断裂 #{{ audit.first_bad_seq }}</template
            >。哈希链只能<strong>检测</strong>篡改，不能阻止能重算整条链的攻击者。
          </p>
        </div>
        <p v-else class="hint">正在校验…</p>
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
