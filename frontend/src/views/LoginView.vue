<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'
import { api } from '../api'

const auth = useAuth()
const router = useRouter()

const studentId = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)
const mode = ref<'login' | 'register'>('login')
const regName = ref('')

async function submit() {
  error.value = ''
  loading.value = true
  try {
    if (mode.value === 'register') {
      await api.register(studentId.value.trim(), regName.value.trim(), password.value)
      mode.value = 'login'
    }
    await auth.login(studentId.value.trim(), password.value)
    router.push('/elections')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card" style="max-width: 460px; margin: 40px auto">
    <h2 v-if="mode === 'login'">🔐 选民登录</h2>
    <h2 v-else>📝 注册</h2>

    <div v-if="error" class="alert a-bad">{{ error }}</div>

    <label class="fl">学号</label>
    <input v-model="studentId" placeholder="HK12345678" @keyup.enter="submit" />

    <template v-if="mode === 'register'">
      <div style="height: 12px"></div>
      <label class="fl">姓名</label>
      <input v-model="regName" placeholder="陈大文" />
    </template>

    <div style="height: 12px"></div>
    <label class="fl">密码</label>
    <input v-model="password" type="password" placeholder="至少 8 位" @keyup.enter="submit" />

    <div style="height: 16px"></div>
    <button class="btn" :disabled="loading" @click="submit">
      {{ loading ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录' }}
    </button>

    <div style="height: 12px"></div>
    <div class="mut">
      {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
      <a href="#" @click.prevent="mode = mode === 'login' ? 'register' : 'login'">
        {{ mode === 'login' ? '注册' : '去登录' }}
      </a>
    </div>
  </div>
</template>
