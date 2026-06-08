<template>
  <div class="not-found-page">
    <div class="not-found-content">
      <h1>404</h1>
      <p>抱歉，您访问的页面不存在</p>
      <router-link to="/" class="btn-home">返回首页</router-link>
    </div>
  </div>
</template>

<style scoped>
.not-found-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 80vh;
  text-align: center;
  background: #0a0a0a;
  color: #fff;
  padding: 24px;
}
.not-found-page h1 {
  font-size: 5rem;
  color: #6366f1;
  margin: 0;
  line-height: 1;
}
.not-found-page p {
  font-size: 1.1rem;
  color: #a1a1aa;
  margin: 1rem 0 2rem;
}
.btn-home {
  display: inline-block;
  padding: 0.75rem 2rem;
  background: #6366f1;
  color: #fff;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 600;
}
.btn-home:hover {
  filter: brightness(1.08);
}
</style>
