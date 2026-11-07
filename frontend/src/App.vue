<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from './stores/auth'
import hkmuLogo from './assets/hkmu-logo.png'

const auth = useAuth()
const router = useRouter()
const route = useRoute()

onMounted(() => auth.restore())

function logout() {
  auth.logout()
  router.push('/login')
}

const navItems = [
  { to: '/elections', label: 'Elections' },
  { to: '/receipt', label: 'Verify receipt' },
]
</script>

<template>
  <header class="topbar">
    <div class="container topbar-inner">
      <router-link to="/elections" class="brand">
        <img :src="hkmuLogo" class="brand-logo" alt="Hong Kong Metropolitan University (HKMU)" />
        <span class="brand-text">
          <strong>Election Management &amp; Voting System</strong>
          <small>COMP 3500SEF · Group project</small>
        </span>
      </router-link>

      <nav class="nav" aria-label="Main navigation">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-link"
          :class="{ active: route.path.startsWith(item.to) }"
        >
          {{ item.label }}
        </router-link>
        <router-link
          v-if="auth.isStaff"
          to="/admin"
          class="nav-link"
          :class="{ active: route.path.startsWith('/admin') }"
        >
          Admin
        </router-link>
      </nav>

      <div class="account">
        <template v-if="auth.user">
          <span class="who">
            <span class="who-name">{{ auth.user.name || auth.user.student_id }}</span>
            <span class="badge badge-muted badge-plain">{{ auth.user.role }}</span>
          </span>
          <button class="btn btn-ghost btn-sm" @click="logout">Sign out</button>
        </template>
        <router-link v-else to="/login" class="btn btn-sm">Sign in</router-link>
      </div>
    </div>
  </header>

  <main>
    <router-view />
  </main>

  <footer class="site-footer">
    <div class="container footer-inner">
      <span>COMP 3500SEF / 8500SEF Software Engineering · Student project</span>
      <span class="muted">Course assignment — not an official HKMU system</span>
    </div>
  </footer>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: saturate(180%) blur(8px);
  border-bottom: 1px solid var(--line);
}

.topbar-inner {
  display: flex;
  align-items: center;
  gap: var(--s-5);
  height: var(--topbar-h);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  color: var(--ink);
  text-decoration: none;
  min-width: 0;
}
.brand:hover {
  text-decoration: none;
}

.brand-logo {
  height: 26px;
  width: auto;
  flex: none;
  display: block;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  min-width: 0;
}
.brand-text strong {
  font-size: var(--text-base);
  font-weight: 650;
  letter-spacing: -0.01em;
  white-space: nowrap;
}
.brand-text small {
  font-size: var(--text-xs);
  color: var(--muted);
  white-space: nowrap;
}

.nav {
  display: flex;
  align-items: center;
  gap: var(--s-1);
  margin-left: var(--s-3);
}

.nav-link {
  padding: 6px var(--s-3);
  border-radius: var(--r-sm);
  color: var(--ink-soft);
  font-size: var(--text-sm);
  font-weight: 550;
  text-decoration: none;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.nav-link:hover {
  background: var(--surface-2);
  color: var(--ink);
  text-decoration: none;
}
.nav-link.active {
  background: var(--brand-soft);
  color: var(--brand-dark);
}

.account {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--s-3);
}

.who {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  font-size: var(--text-sm);
  color: var(--ink-soft);
}
.who-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.site-footer {
  border-top: 1px solid var(--line);
  background: var(--surface);
  padding: var(--s-4) 0;
  margin-top: var(--s-6);
}

.footer-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  flex-wrap: wrap;
  font-size: var(--text-xs);
  color: var(--ink-soft);
}

@media (max-width: 720px) {
  .brand-text small,
  .who-name {
    display: none;
  }
  .topbar-inner {
    gap: var(--s-3);
  }
  .nav {
    margin-left: 0;
  }
}
</style>
