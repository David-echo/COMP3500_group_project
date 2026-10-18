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

const canSubmit = computed(() => rank.value.length > 0 && !submitting.value)

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
</script>

<template>
  <div class="card">
    <h2>{{ election?.title ?? '投票' }}</h2>

    <div v-if="error" class="alert a-bad">{{ error }}</div>

    <div v-if="receipt" class="alert a-ok">
      ✅ 投票成功！请保存凭证码
      <div class="mono" style="font-size: 22px; letter-spacing: 2px; margin: 8px 0">
        {{ receipt.code }}
      </div>
      <div class="mut">审计记录 #{{ receipt.auditSeq }} · 凭证不含您的选择内容</div>
      <div class="row" style="margin-top: 12px">
        <button class="btn sm ghost" @click="router.push('/receipt')">去核验凭证</button>
        <button class="btn sm" @click="router.push('/elections')">返回选举列表</button>
      </div>
    </div>

    <template v-else-if="election && position">
      <div class="alert a-info">
        请为【{{ position.title }}】选择候选人：
        {{ isIrv ? '按偏好顺序依次点击（第 1 次点击 = 第 1 选择）' : '单选，点击候选即可选中' }}
      </div>

      <div
        v-for="c in position.candidates"
        :key="c.idx"
        class="cand"
        :class="{ sel: rank.includes(c.idx) }"
        @click="toggle(c.idx)"
      >
        <div class="rank" :class="{ on: rank.includes(c.idx) }">
          {{ rank.includes(c.idx) ? rank.indexOf(c.idx) + 1 : '' }}
        </div>
        <div>
          <div style="font-weight: 600">{{ c.name }}</div>
          <div class="mut">{{ c.party }}</div>
        </div>
      </div>

      <div class="mut" style="margin: 10px 0">
        已选择：
        <b v-if="rank.length">
          {{ rank.map((i) => position!.candidates.find((c) => c.idx === i)?.name).join(' → ') }}
        </b>
        <span v-else>尚未选择</span>
      </div>

      <div class="row">
        <button class="btn" :disabled="!canSubmit" @click="submit">
          {{ submitting ? '提交中…' : '确认投票' }}
        </button>
        <button class="btn ghost" @click="router.push('/elections')">← 返回</button>
      </div>
    </template>

    <div v-else class="mut">加载中…</div>
  </div>
</template>
