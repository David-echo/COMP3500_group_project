<script setup lang="ts">
import { ref } from 'vue'
import { api, type ReceiptInfo } from '../api'

const code = ref('')
const info = ref<ReceiptInfo | null>(null)
const error = ref('')
const loading = ref(false)

/** 后端返回 ISO 时间（含微秒），这里只显示到秒 */
function fmtTime(v?: string) {
  if (!v) return '—'
  return v.replace('T', ' ').slice(0, 19)
}

async function verify() {
  error.value = ''
  info.value = null
  const value = code.value.trim()
  if (!value) {
    error.value = '请输入凭证码'
    return
  }
  loading.value = true
  try {
    info.value = await api.receipt(value)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="container page receipt-page">
    <header class="page-head">
      <div>
        <h1 class="page-title">凭证核验</h1>
        <p class="page-sub">输入投票后拿到的凭证码，确认选票是否已计入</p>
      </div>
    </header>

    <section class="card">
      <div class="card-body">
        <form class="verify-form" @submit.prevent="verify">
          <label class="label" for="code">凭证码</label>
          <div class="verify-row">
            <input
              id="code"
              v-model="code"
              class="input mono"
              placeholder="XXXX-XXXX-XXXX"
              autocomplete="off"
              spellcheck="false"
            />
            <button class="btn" type="submit" :disabled="loading">
              {{ loading ? '核验中…' : '核验' }}
            </button>
          </div>
          <p class="hint mt-3">
            凭证<strong>不包含</strong>你的选择内容 —— 这是有意设计，防止凭证被用于
            向他人证明投票选择（防胁迫与贿选）。
          </p>
        </form>

        <div v-if="error" class="alert alert-danger mt-5" role="alert">{{ error }}</div>

        <div v-else-if="info" class="mt-5 rise-in">
          <div v-if="!info.found" class="alert alert-danger">
            ✕ {{ info.message }}
          </div>

          <div v-else class="result">
            <div class="result-head">
              <span class="result-icon" aria-hidden="true">✓</span>
              <div>
                <h2 class="card-title">{{ info.message }}</h2>
                <p class="page-sub">该凭证对应的选票状态</p>
              </div>
            </div>

            <dl class="result-grid">
              <div class="result-item">
                <dt>选举</dt>
                <dd>{{ info.election_title }}</dd>
              </div>
              <div class="result-item">
                <dt>投票时间</dt>
                <dd class="mono">{{ fmtTime(info.cast_at) }}</dd>
              </div>
              <div class="result-item">
                <dt>是否计入</dt>
                <dd>
                  <span class="badge" :class="info.counted ? 'badge-open' : 'badge-closed'">
                    {{ info.counted ? '已计入' : '未计入' }}
                  </span>
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.receipt-page {
  max-width: 680px;
}

.verify-form {
  max-width: 460px;
}

.verify-row {
  display: flex;
  gap: var(--s-3);
}

.verify-row .input {
  flex: 1 1 auto;
}

.result-head {
  display: flex;
  align-items: flex-start;
  gap: var(--s-3);
  padding-bottom: var(--s-4);
  border-bottom: 1px solid var(--line-soft);
}

.result-icon {
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

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--s-4);
  margin: var(--s-4) 0 0;
}

.result-item dt {
  font-size: var(--text-xs);
  color: var(--muted);
  margin-bottom: 4px;
}

.result-item dd {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ink);
  word-break: break-word;
}

@media (max-width: 520px) {
  .verify-row {
    flex-direction: column;
  }
}
</style>
