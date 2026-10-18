<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from './stores/auth'

const auth = useAuth()
const router = useRouter()

onMounted(() => auth.restore())

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <header>
    <div>
      <h1>🗳️ 选举管理与投票系统</h1>
    </div>
    <div class="row">
      <span v-if="auth.user" class="chip">{{ auth.user.name }}（{{ auth.user.role }}）</span>
      <router-link v-if="auth.isStaff" to="/admin" class="chip">管理台</router-link>
      <router-link to="/elections" class="chip">选举</router-link>
      <router-link to="/receipt" class="chip">凭证核验</router-link>
      <button v-if="auth.user" class="btn sm ghost" @click="logout">退出</button>
    </div>
  </header>
  <div class="wrap">
    <router-view />
  </div>
</template>

<style scoped>
header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 28px; color: #fff; gap: 16px; flex-wrap: wrap;
  background: linear-gradient(120deg, #1e3a8a, #2f5bd7 60%, #4f7ef0);
}
h1 { margin: 0; font-size: 18px; }
.chip {
  background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28);
  padding: 4px 11px; border-radius: 100px; font-size: 12px; color: #fff;
  text-decoration: none;
}
</style>
