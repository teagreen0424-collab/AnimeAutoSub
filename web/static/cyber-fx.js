/**
 * AnimeAutoSub Ultra-Cyberpunk FX Engine (web/static/cyber-fx.js)
 * 2026/2027 Cutting-Edge Visual Effects:
 * 1. Deep Space Neural Canvas (交互式星空神经网络流光背景)
 * 2. 3D Tilt & Holographic Spotlight Sheen on Task Cards (卡片三维拟态与全息探照高光)
 * 3. Cyber Button Ripple & Energy Pulses (微交互动态粒子反馈)
 */

class CyberFXEngine {
  constructor() {
    this.canvas = null;
    this.ctx = null;
    this.particles = [];
    this.particleCount = 48;
    this.maxDistance = 140;
    this.mouse = { x: null, y: null, radius: 160 };
    this.animId = null;
    this.isPaused = false;

    this.initCanvas();
    this.initCardInteractions();
    this.initVisibilityListener();
  }

  /* ==========================================================================
     1. Neural Canvas Background (深空神经网络流动背景)
     ========================================================================== */
  initCanvas() {
    this.canvas = document.getElementById("cyberCanvas");
    if (!this.canvas) {
      this.canvas = document.createElement("canvas");
      this.canvas.id = "cyberCanvas";
      this.canvas.className = "cyber-canvas";
      document.body.prepend(this.canvas);
    }

    // 强内联样式兜底：确保脱离正常文档流，绝不影响或推挤页面正常结构
    this.canvas.style.position = "fixed";
    this.canvas.style.top = "0";
    this.canvas.style.left = "0";
    this.canvas.style.width = "100vw";
    this.canvas.style.height = "100vh";
    this.canvas.style.pointerEvents = "none";
    this.canvas.style.zIndex = "0";

    this.ctx = this.canvas.getContext("2d", { alpha: true });
    this.resizeCanvas();

    window.addEventListener("resize", () => this.resizeCanvas(), { passive: true });
    window.addEventListener("mousemove", (e) => {
      this.mouse.x = e.clientX;
      this.mouse.y = e.clientY;
    }, { passive: true });

    window.addEventListener("mouseout", () => {
      this.mouse.x = null;
      this.mouse.y = null;
    });

    this.spawnParticles();
    this.render();
  }

  resizeCanvas() {
    if (!this.canvas) return;
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  spawnParticles() {
    this.particles = [];
    const colors = [
      "rgba(0, 240, 255, 0.8)",   // Electric Cyan
      "rgba(168, 85, 247, 0.75)", // Cyber Purple
      "rgba(56, 189, 248, 0.7)",  // Sky Blue
      "rgba(236, 72, 153, 0.6)"   // Neon Pink
    ];

    for (let i = 0; i < this.particleCount; i++) {
      this.particles.push({
        x: Math.random() * this.canvas.width,
        y: Math.random() * this.canvas.height,
        vx: (Math.random() - 0.5) * 0.45,
        vy: (Math.random() - 0.5) * 0.45,
        radius: Math.random() * 1.8 + 0.8,
        color: colors[Math.floor(Math.random() * colors.length)],
        baseAlpha: Math.random() * 0.5 + 0.2,
        pulseSpeed: Math.random() * 0.02 + 0.01,
        pulseVal: Math.random() * Math.PI
      });
    }
  }

  render() {
    if (this.isPaused) return;

    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    // 绘制与更新粒子
    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];

      // 移动
      p.x += p.vx;
      p.y += p.vy;

      // 边缘反弹
      if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
      if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;

      // 鼠标交互引力/排斥
      if (this.mouse.x !== null && this.mouse.y !== null) {
        const dx = this.mouse.x - p.x;
        const dy = this.mouse.y - p.y;
        const dist = Math.hypot(dx, dy);
        if (dist < this.mouse.radius) {
          const force = (1 - dist / this.mouse.radius) * 0.6;
          p.x -= (dx / dist) * force;
          p.y -= (dy / dist) * force;
        }
      }

      // 呼吸脉冲
      p.pulseVal += p.pulseSpeed;
      const curRadius = p.radius + Math.sin(p.pulseVal) * 0.5;

      // 粒子光晕
      this.ctx.beginPath();
      this.ctx.arc(p.x, p.y, Math.max(0.2, curRadius), 0, Math.PI * 2);
      this.ctx.fillStyle = p.color;
      this.ctx.shadowBlur = 10;
      this.ctx.shadowColor = p.color;
      this.ctx.fill();

      // 连接近邻粒子连线 (神经网络突触)
      for (let j = i + 1; j < this.particles.length; j++) {
        const p2 = this.particles[j];
        const dx = p.x - p2.x;
        const dy = p.y - p2.y;
        const dist = Math.hypot(dx, dy);

        if (dist < this.maxDistance) {
          const alpha = (1 - dist / this.maxDistance) * 0.22;
          this.ctx.beginPath();
          this.ctx.moveTo(p.x, p.y);
          this.ctx.lineTo(p2.x, p2.y);
          this.ctx.strokeStyle = `rgba(56, 189, 248, ${alpha})`;
          this.ctx.lineWidth = 0.85;
          this.ctx.shadowBlur = 0;
          this.ctx.stroke();
        }
      }

      // 鼠标与粒子之间的动态连线
      if (this.mouse.x !== null && this.mouse.y !== null) {
        const mDist = Math.hypot(this.mouse.x - p.x, this.mouse.y - p.y);
        if (mDist < 120) {
          const mAlpha = (1 - mDist / 120) * 0.35;
          this.ctx.beginPath();
          this.ctx.moveTo(p.x, p.y);
          this.ctx.lineTo(this.mouse.x, this.mouse.y);
          this.ctx.strokeStyle = `rgba(0, 240, 255, ${mAlpha})`;
          this.ctx.lineWidth = 1.0;
          this.ctx.stroke();
        }
      }
    }

    this.animId = requestAnimationFrame(() => this.render());
  }

  initVisibilityListener() {
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        this.isPaused = true;
        if (this.animId) cancelAnimationFrame(this.animId);
      } else {
        this.isPaused = false;
        this.render();
      }
    });
  }

  /* ==========================================================================
     2. 3D Card Hover Tilt & Holographic Spotlight (卡片全息探照与三维倾角)
     ========================================================================== */
  initCardInteractions() {
    this.attachCardEffects();

    // 当任务列表通过 innerHTML 重新渲染时，自动重绑
    const container = document.getElementById("tasksListContainer");
    if (container) {
      const observer = new MutationObserver(() => {
        this.attachCardEffects();
      });
      observer.observe(container, { childList: true, subtree: false });
    }
  }

  attachCardEffects() {
    const cards = document.querySelectorAll(".task-card, .stat-card");
    cards.forEach(card => {
      if (card.__cyberFxBound) return;
      card.__cyberFxBound = true;

      card.addEventListener("mousemove", (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        // 设置全息探照灯坐标
        card.style.setProperty("--mouse-x", `${x}px`);
        card.style.setProperty("--mouse-y", `${y}px`);

        // 计算 3D 偏转微动效 (仅限 task-card)
        if (card.classList.contains("task-card")) {
          const centerX = rect.width / 2;
          const centerY = rect.height / 2;
          const rotateX = ((y - centerY) / centerY) * -5.0; // 最大 -5deg 到 5deg
          const rotateY = ((x - centerX) / centerX) * 5.0;
          card.style.transform = `perspective(1000px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) translateY(-4px)`;
        }
      });

      card.addEventListener("mouseleave", () => {
        if (card.classList.contains("task-card")) {
          card.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg) translateY(0)";
        }
      });
    });
  }
}

// 自动实例化
if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    window.cyberFX = new CyberFXEngine();
  });
}
