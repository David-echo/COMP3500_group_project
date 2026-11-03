<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'
import { api } from '../api'
import hkmuLogo from '../assets/hkmu-logo.png'

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

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
  error.value = ''
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <!-- 左侧说明区 -->
      <aside class="auth-aside">
        <div class="auth-aside-inner">
          <div class="auth-logo">
            <img :src="hkmuLogo" alt="香港都會大學 HKMU" />
          </div>
          <span class="auth-badge">COMP 3500SEF</span>
          <h1 class="auth-h1">选举管理<br />与投票系统</h1>
          <p class="auth-lead">
            投票匿名、结果可审计。<br />
            每一张选票都能被验证，但没有人能查出你投给了谁。
          </p>
          <ul class="auth-points">
            <li><span class="dot" aria-hidden="true"></span>一人一票，由数据库约束保证</li>
            <li><span class="dot" aria-hidden="true"></span>凭证码可核验，且不含选择内容</li>
            <li><span class="dot" aria-hidden="true"></span>审计日志哈希链，篡改可检测</li>
          </ul>
        </div>
      </aside>

      <!-- 右侧表单 -->
      <section class="auth-form">
        <header class="auth-form-head">
          <h2 class="card-title">{{ mode === 'login' ? '登录' : '注册' }}</h2>
          <p class="page-sub">
            {{ mode === 'login' ? '使用学号与密码进入系统' : '创建一个新账号，注册后自动登录' }}
          </p>
        </header>

        <div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

        <form @submit.prevent="submit">
          <div class="field">
            <label class="label" for="studentId">学号</label>
            <input
              id="studentId"
              v-model="studentId"
              class="input"
              placeholder="HK12345678"
              autocomplete="username"
            />
          </div>

          <div v-if="mode === 'register'" class="field">
            <label class="label" for="regName">姓名</label>
            <input id="regName" v-model="regName" class="input" placeholder="陈大文" />
          </div>

          <div class="field">
            <label class="label" for="password">密码</label>
            <input
              id="password"
              v-model="password"
              class="input"
              type="password"
              placeholder="至少 8 位"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
            />
          </div>

          <button class="btn btn-block mt-5" type="submit" :disabled="loading">
            {{ loading ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录' }}
          </button>
        </form>

        <p class="auth-switch">
          {{ mode === 'login' ? '还没有账号？' : '已有账号？' }}
          <button type="button" class="linkbtn" @click="switchMode">
            {{ mode === 'login' ? '注册' : '去登录' }}
          </button>
        </p>

        <p class="hint auth-hint">
          演示环境：选民 <code class="mono">HK100000</code>–<code class="mono">HK100029</code> /
          <code class="mono">voter12345</code>；管理员 <code class="mono">ADMIN001</code> /
          <code class="mono">admin12345</code>
        </p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  display: grid;
  place-items: center;
  min-height: calc(100vh - var(--topbar-h));
  padding: var(--s-6) var(--s-4);
}

.auth-card {
  display: grid;
  grid-template-columns: 1.05fr 1fr;
  width: 100%;
  max-width: 880px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-md);
  overflow: hidden;
}

/* 左侧 */
.auth-aside {
  background: linear-gradient(158deg, #00456e 0%, #00619b 48%, #0078c0 100%);
  color: #fff;
  padding: var(--s-6);
  display: flex;
  align-items: center;
}

.auth-aside-inner {
  max-width: 340px;
}

.auth-logo {
  display: flex;
  width: fit-content;
  align-items: center;
  background: #fff;
  border-radius: var(--r-sm);
  padding: 8px 12px;
  margin-bottom: var(--s-4);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
}

.auth-logo img {
  height: 30px;
  width: auto;
  display: block;
}

.auth-badge {
  display: inline-block;
  padding: 3px 10px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: var(--r-pill);
  font-size: var(--text-xs);
  letter-spacing: 0.05em;
  opacity: 0.9;
}

.auth-h1 {
  margin-top: var(--s-4);
  font-size: 28px;
  line-height: 1.3;
  font-weight: 680;
  letter-spacing: -0.02em;
}

.auth-lead {
  margin-top: var(--s-3);
  font-size: var(--text-sm);
  line-height: 1.75;
  opacity: 0.86;
}

.auth-points {
  margin-top: var(--s-5);
  padding: 0;
  list-style: none;
  display: grid;
  gap: var(--s-3);
  font-size: var(--text-sm);
  opacity: 0.92;
}

.auth-points li {
  display: flex;
  align-items: flex-start;
  gap: var(--s-2);
}

.dot {
  width: 6px;
  height: 6px;
  margin-top: 7px;
  border-radius: 50%;
  background: var(--accent);
  flex: none;
}

/* 右侧 */
.auth-form {
  padding: var(--s-6);
  display: flex;
  flex-direction: column;
}

.auth-form-head {
  margin-bottom: var(--s-5);
}

.auth-switch {
  margin-top: var(--s-4);
  font-size: var(--text-sm);
  color: var(--muted);
}

.linkbtn {
  border: none;
  background: none;
  padding: 0;
  color: var(--brand);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.linkbtn:hover {
  text-decoration: underline;
}

.auth-hint {
  margin-top: auto;
  padding-top: var(--s-5);
  line-height: 1.9;
}

.auth-hint code {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 0 4px;
  font-size: 11px;
}

@media (max-width: 760px) {
  .auth-card {
    grid-template-columns: 1fr;
  }
  .auth-aside {
    padding: var(--s-5);
  }
  .auth-h1 {
    font-size: 22px;
  }
  .auth-points {
    display: none;
  }
}
</style>
