<script setup lang="ts">
import { ref } from 'vue'
import { api, type ReceiptInfo } from '../api'

const code = ref('')
const info = ref<ReceiptInfo | null>(null)
const error = ref('')
const loading = ref(false)


function fmtTime(v?: string) {
  if (!v) return '—'
  return v.replace('T', ' ').slice(0, 19)
}

async function verify() {
  error.value = ''
  info.value = null
  const value = code.value.trim()
  if (!value) {
    error.value = 'Please enter a receipt code'
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
        <h1 class="page-title">Verify receipt</h1>
        <p class="page-sub">Enter the receipt code you received after voting to confirm your ballot was counted</p>
      </div>
    </header>

    <section class="card">
      <div class="card-body">
        <form class="verify-form" @submit.prevent="verify">
          <label class="label" for="code">Receipt code</label>
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
              {{ loading ? 'Checking…' : 'Verify' }}
            </button>
          </div>
          <p class="hint mt-3">
            The receipt does <strong>not</strong> contain your choice. This is deliberate:
            it prevents the receipt from being used to prove how you voted.
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
                <p class="page-sub">Ballot status for this receipt</p>
              </div>
            </div>

            <dl class="result-grid">
              <div class="result-item">
                <dt>Election</dt>
                <dd>{{ info.election_title }}</dd>
              </div>
              <div class="result-item">
                <dt>Voted at</dt>
                <dd class="mono">{{ fmtTime(info.cast_at) }}</dd>
              </div>
              <div class="result-item">
                <dt>Counted</dt>
                <dd>
                  <span class="badge" :class="info.counted ? 'badge-open' : 'badge-closed'">
                    {{ info.counted ? 'Counted' : 'Not counted' }}
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
