<script setup lang="ts">
import { ref } from 'vue'
import { api, type ReceiptInfo } from '../api'

const code = ref('')
const info = ref<ReceiptInfo | null>(null)
const error = ref('')

async function verify() {
  error.value = ''
  info.value = null
  try {
    info.value = await api.receipt(code.value.trim())
  } catch (e) {
    error.value = (e as Error).message
  }
}
</script>

<template>
  <div class="card" style="max-width: 620px; margin: 0 auto">
    <h2>🔎 凭证核验</h2>
    <div class="alert a-info">
      输入投票后拿到的凭证码，确认「我的票已计入且未被修改」。
      <b>凭证刻意不包含选择内容</b>，因此无法用来向他人证明投了谁。
    </div>

    <div v-if="error" class="alert a-bad">{{ error }}</div>

    <div class="row">
      <input
        v-model="code"
        class="mono"
        placeholder="XXXX-XXXX-XXXX"
        style="max-width: 300px"
        @keyup.enter="verify"
      />
      <button class="btn" @click="verify">核验</button>
    </div>

    <div v-if="info" style="margin-top: 14px">
      <div v-if="!info.found" class="alert a-bad">❌ {{ info.message }}</div>
      <div v-else class="alert a-ok">
        ✅ {{ info.message }}
        <div class="mut" style="margin-top: 6px">
          选举：{{ info.election_title }}<br />
          投票时间：{{ info.cast_at }}
        </div>
      </div>
    </div>
  </div>
</template>
