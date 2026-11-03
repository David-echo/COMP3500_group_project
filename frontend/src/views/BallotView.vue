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
    /* 剪贴板不可用时忽略，用户可手动选中 */
  }
}
</script>

<template>
  <div class="container page ballot-page">
    <!-- 顶部返回 + 标题 -->
    <header class="page-head">
      <div>
        <button class="backlink" @click="router.push('/elections')">← 返回选举列表</button>
        <h1 class="page-title mt-3">{{ election?.title ?? '投票' }}</h1>
        <p v-if="position" class="page-sub">{{ position.title }}</p>
      </div>
      <span v-if="election" class="badge" :class="`badge-${election.status}`">
        {{ election.status_label }}
      </span>
    </header>

    <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

    <!-- 投票成功 -->
    <section v-if="receipt" class="card receipt-card rise-in">
      <div class="card-body">
        <div class="receipt-head">
          <span class="receipt-icon" aria-hidden="true">✓</span>
          <div>
            <h2 class="card-title">投票已完成</h2>
            <p class="page-sub">请保存下面的凭证码，可用于确认你的选票已计入。</p>
          </div>
        </div>

        <div class="receipt-code">
          <span class="mono">{{ receipt.code }}</span>
          <button class="btn btn-ghost btn-sm" @click="copyCode">
            {{ copied ? '已复制' : '复制' }}
          </button>
        </div>

        <p class="hint">
          审计记录 #{{ receipt.auditSeq }} · 凭证<strong>不包含</strong>你的选择内容，
          因此无法用来向他人证明投给了谁。
        </p>

        <div class="row mt-5">
          <button class="btn btn-ghost" @click="router.push('/receipt')">去核验凭证</button>
          <button class="btn" @click="router.push('/elections')">返回选举列表</button>
        </div>
      </div>
    </section>

    <!-- 不可投票 -->
    <section v-else-if="notOpen" class="card">
      <div class="card-body">
        <div class="alert alert-info">
          该选举当前状态为「{{ election?.status_label }}」，不接受投票。
        </div>
        <div class="row mt-4">
          <button class="btn btn-ghost" @click="router.push('/elections')">返回</button>
        </div>
      </div>
    </section>

    <!-- 选票 -->
    <section v-else-if="election && position" class="ballot-grid">
      <div class="card">
        <div class="card-head">
          <h2 class="card-title">选择候选人</h2>
          <span class="hint">
            {{ isIrv ? '按偏好顺序依次点击' : '单选，点击即可选中' }}
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
              <small>{{ c.party || '独立' }}</small>
            </span>
            <span v-if="rank.includes(c.idx)" class="tick" aria-hidden="true">✓</span>
          </li>
        </ul>
      </div>

      <!-- 提交区 -->
      <aside class="card summary">
        <div class="card-body">
          <h2 class="card-title">确认投票</h2>

          <div class="summary-body">
            <p class="muted text-xs">你已选择</p>
            <ol v-if="selectedNames.length" class="summary-list">
              <li v-for="(n, i) in selectedNames" :key="i">
                <span v-if="rank.length > 1" class="idx">{{ i + 1 }}</span>
                {{ n }}
              </li>
            </ol>
            <p v-else class="empty-inline">尚未选择候选人</p>
          </div>

          <button class="btn btn-block" :disabled="!canSubmit" @click="submit">
            {{ submitting ? '提交中…' : '确认投票' }}
          </button>

          <p class="hint mt-3">
            {{ isIrv
              ? '排序复选制：只选一个也可以提交。'
              : '单选制：只能选择一名候选人。' }}
            提交后不能修改。
          </p>
        </div>
      </aside>
    </section>

    <div v-else class="card empty">加载中…</div>
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

/* 右侧提交区 */
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

/* 凭证卡片 */
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
