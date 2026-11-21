<script setup>
import ChatBox from './components/ChatBox.vue'
</script>

<template>
  <main>
    <ChatBox />
  </main>
</template>

<style>
*, *::before, *::after {
  box-sizing: border-box;
}

body {
  margin: 0;
  font: 15px/1.6 system-ui, "Microsoft YaHei", sans-serif;
  color: #1e293b;
}

#app {
  min-height: 100vh;
  background: radial-gradient(circle at 50% 0%, #f1f5f9 0%, #e2e8f0 100%);
}
</style>
