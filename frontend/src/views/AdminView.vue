<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { api, type Election, type ResultRow } from '../api'

const elections = ref<Election[]>([])
const error = ref('')
const results = ref<ResultRow[] | null>(null)
const resultsMsg = ref('')
const integrity = ref<{ all_passed: boolean; checks: Array<{ name: string; passed: boolean; detail: string }> } | null>(null)
const audit = ref<{ ok: boolean; length: number; first_bad_seq: number | null; message: string } | null>(null)
const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

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
    if (r.published) await nextTick(), renderChart()
    else if (chart) chart.clear()
  } catch (err) {
    error.value = (err as Error).message
  }
}

function renderChart() {
  if (!chartEl.value || !results.value?.length) return
  if (!chart) chart = echarts.init(chartEl.value)
  const row = results.value[0]
  const data = Object.entries(row.counts).map(([k, v]) => ({
    name: row.winner_idx === Number(k) ? `★ ${k}` : k,
    value: v,
  }))
  chart.setOption({
    tooltip: {},
    xAxis: { type: 'category', data: data.map((d) => d.name) },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: data.map((d) => d.value), barMaxWidth: 56 }],
  })
  chart.resize()
}

async function checkIntegrity(e: Election) {
  integrity.value = await api.integrity(e.id)
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
  <div v-if="error" class="alert a-bad">{{ error }}</div>

  <div class="card">
    <h2>🗂️ 选举管理</h2>
    <table>
      <thead>
        <tr><th>选举</th><th>状态</th><th>投票率</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="e in elections" :key="e.id">
          <td>
            <b>{{ e.title }}</b>
            <div class="mut">{{ e.tally_method === 'irv' ? '排序复选制' : '单选制' }}</div>
          </td>
          <td><span class="badge" :class="`b-${e.status}`">{{ e.status_label }}</span></td>
          <td>{{ e.turnout.percent }}%</td>
          <td>
            <div class="row">
              <button v-if="e.status === 'scheduled'" class="btn sm ghost" @click="setStatus(e, 'open')">开放投票</button>
              <button v-if="e.status === 'open'" class="btn sm ghost" @click="setStatus(e, 'closed')">截止</button>
              <button v-if="e.status === 'closed'" class="btn sm" @click="publish(e)">计票公示</button>
              <button v-if="e.status !== 'scheduled'" class="btn sm ghost" @click="showResults(e)">查看结果</button>
              <button class="btn sm ghost" @click="checkIntegrity(e)">完整性</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>📊 计票结果</h2>
    <div v-if="resultsMsg" class="alert a-info">{{ resultsMsg }}</div>
    <div v-if="results?.length">
      <div class="row" style="margin-bottom: 10px">
        <span class="badge b-pub">{{ results[0].tally_label }}</span>
        <span class="mut">有效票 {{ results[0].ballot_count }}</span>
        <span v-if="results[0].winner_name" class="badge b-open">当选：{{ results[0].winner_name }}</span>
      </div>
      <div class="mut mono" style="word-break: break-all">摘要：{{ results[0].digest }}</div>
    </div>
    <div ref="chartEl" style="height: 280px; margin-top: 12px"></div>
    <div v-if="!results?.length" class="mut">选择一场已截止的选举并点击「计票公示」或「查看结果」。</div>
  </div>

  <div class="card">
    <h2>✅ 完整性校验</h2>
    <div v-if="integrity">
      <div class="alert" :class="integrity.all_passed ? 'a-ok' : 'a-bad'">
        {{ integrity.all_passed ? '全部不变量通过' : '存在不一致' }}
      </div>
      <table>
        <tbody>
          <tr v-for="c in integrity.checks" :key="c.name">
            <td>{{ c.name }}</td>
            <td>{{ c.passed ? '✅' : '❌' }}</td>
            <td class="mut">{{ c.detail }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="mut">点击选举行里的「完整性」按钮</div>
  </div>

  <div class="card">
    <h2>⛓️ 审计链</h2>
    <div v-if="audit">
      <div class="alert" :class="audit.ok ? 'a-ok' : 'a-bad'">
        {{ audit.ok ? '✅' : '❌' }} {{ audit.message }}
      </div>
      <div class="mut">共 {{ audit.length }} 条记录<span v-if="audit.first_bad_seq">，首条断裂 #{{ audit.first_bad_seq }}</span></div>
    </div>
    <button class="btn sm ghost" style="margin-top: 10px" @click="verifyAudit">重新校验</button>
  </div>
</template>
