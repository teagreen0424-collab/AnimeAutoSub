/**
 * AnimeAutoSub Active Theory Avant-Garde Creative Engine (web/static/cyber-fx.js)
 * Inspired by Active Theory, Locomotive & Awwwards Studio Standards:
 * 1. Interactive Fluid Velocity Field & Chromatic Particle Streamlines (60FPS 流体动力学速度场与色散流线)
 * 2. Active Theory Kinetic Custom Spring Cursor (具有惯性弹簧吸附与物理缩放的动态光标)
 * 3. Real-Time Performance & Telemetry Engine (实时 FPS 帧率遥测、视口坐标与系统心跳)
 * 4. Procedural Mechanical Sound Synthesizer (高阶机械微触感声波合成，零外部资源)
 * 5. Architectural Glare & Bento Hover Physics (极简瑞士解构主义全息折射与悬浮)
 * 6. Smooth Odometer Metric Rollers (高阶流式数字计数器)
 */

class ActiveTheoryEngine {
  constructor() {
    this.canvas = null;
    this.ctx = null;
    this.width = 0;
    this.height = 0;
    this.dpr = 1;

    // 流体动力学速度网格 (Fluid Velocity Grid)
    this.gridSize = 36;
    this.cols = 0;
    this.rows = 0;
    this.velocities = [];
    this.density = [];

    // 鼠标物理运动状态 (Mouse Spring Physics)
    this.mouse = {
      x: -1000,
      y: -1000,
      prevX: -1000,
      prevY: -1000,
      vx: 0,
      vy: 0,
      speed: 0,
      targetX: -1000,
      targetY: -1000,
      isHoveringInteractive: false
    };

    // 流体粒子追踪 (Fluid Streamline Particles)
    this.particles = [];
    this.particleCount = 55;

    // 实时遥测指标 (Live Telemetry: FPS, Delta Time)
    this.lastFrameTime = performance.now();
    this.frameCount = 0;
    this.fps = 60.0;
    this.fpsTimer = performance.now();

    // 纯合成声效引擎
    this.audioCtx = null;
    this.soundEnabled = localStorage.getItem("aas_sound") !== "0";

    // 主题体系 (默认 100% 极简浅色骨白 Alabaster Light)
    this.currentTheme = localStorage.getItem("aas_theme") || "light";

    this.animId = null;
    this.isPaused = false;

    this.initTheme();
    this.initCanvas();
    this.initFluidGrid();
    this.initParticles();
    this.initKineticCursor();
    this.initAudioSynthesizer();
    this.initTelemetryHUD();
    this.initCardPhysics();
    this.initOdometerCounters();
    this.initVisibilityListener();
    this.bindControls();
  }

  /* ==========================================================================
     1. 顶级双主题管理 (默认 100% 极简高雅白境 Alabaster)
     ========================================================================== */
  initTheme() {
    this.applyTheme(this.currentTheme);
  }

  applyTheme(theme) {
    this.currentTheme = theme;
    localStorage.setItem("aas_theme", theme);
    document.body.classList.remove("light-theme", "dark-theme");
    document.body.classList.add(theme === "dark" ? "dark-theme" : "light-theme");

    const themeIcon = document.getElementById("themeIcon");
    if (themeIcon) {
      themeIcon.textContent = theme === "dark" ? "🌙" : "☀️";
    }
    const themeBtn = document.getElementById("btnThemeToggle");
    if (themeBtn) {
      themeBtn.title = theme === "dark" ? "主题: 深空赛博 (点击切换极简白境)" : "主题: 极简白境 (点击切换深空赛博)";
    }
  }

  toggleTheme() {
    const nextTheme = this.currentTheme === "dark" ? "light" : "dark";
    this.applyTheme(nextTheme);
    this.playMechanicalHaptic("toggle");
  }

  toggleSound() {
    this.soundEnabled = !this.soundEnabled;
    localStorage.setItem("aas_sound", this.soundEnabled ? "1" : "0");
    const soundIcon = document.getElementById("soundIcon");
    if (soundIcon) {
      soundIcon.textContent = this.soundEnabled ? "🔊" : "🔇";
    }
    const soundBtn = document.getElementById("btnSoundToggle");
    if (soundBtn) {
      soundBtn.title = this.soundEnabled ? "机械触觉音效: 已开启 (点击静音)" : "机械触觉音效: 已静音 (点击开启)";
    }
    if (this.soundEnabled) {
      this.playMechanicalHaptic("confirm");
    }
  }

  bindControls() {
    const themeBtn = document.getElementById("btnThemeToggle");
    if (themeBtn) {
      themeBtn.addEventListener("click", () => this.toggleTheme());
    }

    const soundBtn = document.getElementById("btnSoundToggle");
    if (soundBtn) {
      soundBtn.addEventListener("click", () => this.toggleSound());
    }
  }

  /* ==========================================================================
     2. Active Theory 机械微触感声波合成器 (Web Audio API Procedural Synth)
     ========================================================================== */
  initAudioSynthesizer() {
    const unlock = () => {
      if (!this.audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (AudioContextClass) this.audioCtx = new AudioContextClass();
      }
      if (this.audioCtx && this.audioCtx.state === "suspended") {
        this.audioCtx.resume();
      }
      window.removeEventListener("pointerdown", unlock);
    };
    window.addEventListener("pointerdown", unlock, { passive: true });
  }

  playMechanicalHaptic(type = "tick") {
    if (!this.soundEnabled || !this.audioCtx) return;
    try {
      if (this.audioCtx.state === "suspended") this.audioCtx.resume();
      const now = this.audioCtx.currentTime;

      if (type === "tick") {
        // Active Theory 标志性高频精密机械微击 (带带通滤波的微秒脉冲，类似高端快门/微动开关)
        const osc = this.audioCtx.createOscillator();
        const filter = this.audioCtx.createBiquadFilter();
        const gain = this.audioCtx.createGain();

        osc.type = "sine";
        osc.frequency.setValueAtTime(1800, now);
        osc.frequency.exponentialRampToValueAtTime(320, now + 0.035);

        filter.type = "bandpass";
        filter.frequency.setValueAtTime(2400, now);
        filter.Q.setValueAtTime(3.0, now);

        gain.gain.setValueAtTime(0.045, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.035);

        osc.connect(filter);
        filter.connect(gain);
        gain.connect(this.audioCtx.destination);

        osc.start(now);
        osc.stop(now + 0.04);
      } else if (type === "hover") {
        // 微型亚音速磁吸接触 (极低电平 1200Hz 20ms)
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(2200, now);
        osc.frequency.exponentialRampToValueAtTime(1200, now + 0.02);
        gain.gain.setValueAtTime(0.012, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.02);
        osc.connect(gain);
        gain.connect(this.audioCtx.destination);
        osc.start(now);
        osc.stop(now + 0.025);
      } else if (type === "confirm" || type === "primary") {
        // 极简工业双音和弦 (F#5 -> C#6 纯净正弦波)
        [739.99, 1108.73].forEach((f, idx) => {
          const osc = this.audioCtx.createOscillator();
          const gain = this.audioCtx.createGain();
          const t = now + idx * 0.045;
          osc.type = "sine";
          osc.frequency.setValueAtTime(f, t);
          gain.gain.setValueAtTime(0.04, t);
          gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
          osc.connect(gain);
          gain.connect(this.audioCtx.destination);
          osc.start(t);
          osc.stop(t + 0.17);
        });
      } else if (type === "toggle") {
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(400, now);
        osc.frequency.exponentialRampToValueAtTime(1100, now + 0.05);
        gain.gain.setValueAtTime(0.035, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.05);
        osc.connect(gain);
        gain.connect(this.audioCtx.destination);
        osc.start(now);
        osc.stop(now + 0.055);
      }
    } catch (_) {}
  }

  /* ==========================================================================
     3. Active Theory 标志性动效光标 (Kinetic Custom Spring Cursor)
     ========================================================================== */
  initKineticCursor() {
    this.cursorRing = document.getElementById("atCursorRing");
    this.cursorDot = document.getElementById("atCursorDot");

    if (!this.cursorRing) {
      this.cursorRing = document.createElement("div");
      this.cursorRing.id = "atCursorRing";
      this.cursorRing.className = "at-cursor-ring";
      document.body.appendChild(this.cursorRing);
    }
    if (!this.cursorDot) {
      this.cursorDot = document.createElement("div");
      this.cursorDot.id = "atCursorDot";
      this.cursorDot.className = "at-cursor-dot";
      document.body.appendChild(this.cursorDot);
    }

    this.cursorPos = { x: -100, y: -100, ringX: -100, ringY: -100 };

    window.addEventListener("mousemove", (e) => {
      this.cursorPos.x = e.clientX;
      this.cursorPos.y = e.clientY;
      this.mouse.targetX = e.clientX;
      this.mouse.targetY = e.clientY;

      // 实时计算鼠标速度矢量 (Velocity Vector)
      if (this.mouse.prevX !== -1000) {
        this.mouse.vx = e.clientX - this.mouse.prevX;
        this.mouse.vy = e.clientY - this.mouse.prevY;
        this.mouse.speed = Math.hypot(this.mouse.vx, this.mouse.vy);
        this.injectFluidVelocity(e.clientX, e.clientY, this.mouse.vx, this.mouse.vy);
      }
      this.mouse.prevX = e.clientX;
      this.mouse.prevY = e.clientY;

      // 检测光标吸附与悬停状态
      const target = e.target.closest("button, .btn, .filter-btn, .task-card, .stat-card, input, select, a");
      if (target) {
        if (!this.mouse.isHoveringInteractive) {
          this.mouse.isHoveringInteractive = true;
          this.cursorRing.classList.add("hover");
          this.cursorDot.classList.add("hover");
          this.playMechanicalHaptic("hover");
        }
      } else {
        if (this.mouse.isHoveringInteractive) {
          this.mouse.isHoveringInteractive = false;
          this.cursorRing.classList.remove("hover");
          this.cursorDot.classList.remove("hover");
        }
      }
    }, { passive: true });

    document.addEventListener("click", (e) => {
      this.cursorRing.classList.add("click");
      setTimeout(() => this.cursorRing.classList.remove("click"), 180);
      const isPrimary = e.target.closest(".btn-primary, #btnConfirmDeleteTask");
      this.playMechanicalHaptic(isPrimary ? "confirm" : "tick");
    });
  }

  /* ==========================================================================
     4. 交互式流体动力学速度网格 (Interactive Fluid Velocity Field)
     ========================================================================== */
  initCanvas() {
    this.canvas = document.getElementById("cyberCanvas");
    if (!this.canvas) {
      this.canvas = document.createElement("canvas");
      this.canvas.id = "cyberCanvas";
      this.canvas.className = "cyber-canvas";
      document.body.prepend(this.canvas);
    }

    // 强内联样式兜底：全屏底层绝对固定
    this.canvas.style.position = "fixed";
    this.canvas.style.top = "0";
    this.canvas.style.left = "0";
    this.canvas.style.width = "100vw";
    this.canvas.style.height = "100vh";
    this.canvas.style.pointerEvents = "none";
    this.canvas.style.zIndex = "0";

    this.ctx = this.canvas.getContext("2d", { alpha: true });
    this.resizeCanvas();

    window.addEventListener("resize", () => {
      this.resizeCanvas();
      this.initFluidGrid();
    }, { passive: true });

    this.render();
  }

  resizeCanvas() {
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.width = window.innerWidth;
    this.height = window.innerHeight;
    this.canvas.width = this.width * this.dpr;
    this.canvas.height = this.height * this.dpr;
    this.ctx.scale(this.dpr, this.dpr);
  }

  initFluidGrid() {
    this.cols = Math.ceil(this.width / this.gridSize) + 1;
    this.rows = Math.ceil(this.height / this.gridSize) + 1;
    const count = this.cols * this.rows;
    this.velocities = new Float32Array(count * 2);
    this.density = new Float32Array(count);
  }

  injectFluidVelocity(x, y, vx, vy) {
    const col = Math.floor(x / this.gridSize);
    const row = Math.floor(y / this.gridSize);
    const radius = 2;

    for (let r = -radius; r <= radius; r++) {
      for (let c = -radius; c <= radius; c++) {
        const gc = col + c;
        const gr = row + r;
        if (gc >= 0 && gc < this.cols && gr >= 0 && gr < this.rows) {
          const idx = (gr * this.cols + gc) * 2;
          const factor = 1 - Math.hypot(c, r) / (radius + 1);
          if (factor > 0) {
            this.velocities[idx] += vx * factor * 0.35;
            this.velocities[idx + 1] += vy * factor * 0.35;
            this.density[gr * this.cols + gc] = Math.min(1.0, this.density[gr * this.cols + gc] + factor * 0.5);
          }
        }
      }
    }
  }

  initParticles() {
    this.particles = [];
    for (let i = 0; i < this.particleCount; i++) {
      this.particles.push({
        x: Math.random() * this.width,
        y: Math.random() * this.height,
        vx: 0,
        vy: 0,
        life: Math.random() * 100,
        maxLife: Math.random() * 120 + 80,
        size: Math.random() * 2.2 + 1.2
      });
    }
  }

  render() {
    if (this.isPaused) return;

    // 1. 实时性能遥测计算 (FPS & Telemetry)
    const now = performance.now();
    const dt = now - this.lastFrameTime;
    this.lastFrameTime = now;
    this.frameCount++;
    if (now - this.fpsTimer >= 500) {
      this.fps = (this.frameCount * 1000) / (now - this.fpsTimer);
      this.frameCount = 0;
      this.fpsTimer = now;
      this.updateTelemetryDisplay();
    }

    // 2. 动效光标平滑弹簧插值 (Spring Lerp)
    this.cursorPos.ringX += (this.cursorPos.x - this.cursorPos.ringX) * 0.18;
    this.cursorPos.ringY += (this.cursorPos.y - this.cursorPos.ringY) * 0.18;

    if (this.cursorRing && this.cursorDot) {
      this.cursorDot.style.transform = `translate3d(${this.cursorPos.x}px, ${this.cursorPos.y}px, 0)`;
      this.cursorRing.style.transform = `translate3d(${this.cursorPos.ringX}px, ${this.cursorPos.ringY}px, 0)`;
    }

    // 3. 画布清空与流体衰减更新
    this.ctx.clearRect(0, 0, this.width, this.height);
    this.updateFluidGrid();

    // 4. 绘制流体色散流线与动效粒子
    this.drawFluidField();

    this.animId = requestAnimationFrame(() => this.render());
  }

  updateFluidGrid() {
    const count = this.cols * this.rows;
    for (let i = 0; i < count; i++) {
      const idx = i * 2;
      // 速度粘滞阻尼衰减
      this.velocities[idx] *= 0.94;
      this.velocities[idx + 1] *= 0.94;
      this.density[i] *= 0.94;
    }
  }

  drawFluidField() {
    const isDark = document.body.classList.contains("dark-theme");

    // 绘制流线微网格与粒子动量跟踪
    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];
      p.life++;

      // 从网格采样流体速度 (Grid Sample)
      const col = Math.floor(p.x / this.gridSize);
      const row = Math.floor(p.y / this.gridSize);
      if (col >= 0 && col < this.cols && row >= 0 && row < this.rows) {
        const idx = (row * this.cols + col) * 2;
        p.vx = p.vx * 0.9 + this.velocities[idx] * 0.15;
        p.vy = p.vy * 0.9 + this.velocities[idx + 1] * 0.15;
      }

      // 自然微扰流漂移
      p.x += p.vx + Math.sin(p.life * 0.02) * 0.4;
      p.y += p.vy - 0.25; // 整体微向上浮升

      if (p.x < 0 || p.x > this.width || p.y < 0 || p.y > this.height || p.life > p.maxLife) {
        p.x = Math.random() * this.width;
        p.y = this.height + 10;
        p.vx = 0;
        p.vy = 0;
        p.life = 0;
      }

      // 粒子光晕透明度
      const progress = p.life / p.maxLife;
      const alpha = Math.sin(progress * Math.PI) * (isDark ? 0.35 : 0.22);
      const fluidSpeed = Math.hypot(p.vx, p.vy);

      // 色散流光
      this.ctx.beginPath();
      this.ctx.arc(p.x, p.y, p.size + fluidSpeed * 0.5, 0, Math.PI * 2);
      this.ctx.fillStyle = isDark
        ? `rgba(0, 240, 255, ${alpha})`
        : `rgba(0, 71, 255, ${alpha})`;
      this.ctx.fill();

      // 速度激波拖尾 (Shockwave Trails)
      if (fluidSpeed > 1.2) {
        this.ctx.beginPath();
        this.ctx.moveTo(p.x, p.y);
        this.ctx.lineTo(p.x - p.vx * 3.5, p.y - p.vy * 3.5);
        this.ctx.strokeStyle = isDark
          ? `rgba(168, 85, 247, ${alpha * 0.8})`
          : `rgba(236, 72, 153, ${alpha * 0.8})`;
        this.ctx.lineWidth = 1.0;
        this.ctx.stroke();
      }
    }
  }

  /* ==========================================================================
     5. 实时 HUD 性能遥测与技术标牌 (Live Telemetry HUD)
     ========================================================================== */
  initTelemetryHUD() {
    this.hudEl = document.getElementById("atTelemetryHUD");
    if (!this.hudEl) {
      this.hudEl = document.createElement("div");
      this.hudEl.id = "atTelemetryHUD";
      this.hudEl.className = "at-telemetry-hud";
      const topbarActions = document.querySelector(".topbar-actions");
      if (topbarActions) {
        topbarActions.prepend(this.hudEl);
      }
    }
  }

  updateTelemetryDisplay() {
    if (!this.hudEl) return;
    const fpsText = this.fps.toFixed(1);
    this.hudEl.innerHTML = `<span class="hud-tag">SYS // LIVE</span><span class="hud-fps">${fpsText} FPS</span>`;
  }

  /* ==========================================================================
     6. 瑞士解构主义 Bento 卡片物理学 (Architectural Glare & Tilt)
     ========================================================================== */
  initCardPhysics() {
    this.attachCardEvents();
    const container = document.getElementById("tasksListContainer");
    if (container) {
      const observer = new MutationObserver(() => this.attachCardEvents());
      observer.observe(container, { childList: true, subtree: false });
    }
  }

  attachCardEvents() {
    const cards = document.querySelectorAll(".task-card, .stat-card, .panel-card, .modal-card");
    cards.forEach(card => {
      if (card.__atBound) return;
      card.__atBound = true;

      card.addEventListener("mousemove", (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        card.style.setProperty("--mouse-x", `${x}px`);
        card.style.setProperty("--mouse-y", `${y}px`);

        if (card.classList.contains("task-card") || card.classList.contains("stat-card")) {
          const centerX = rect.width / 2;
          const centerY = rect.height / 2;
          const rotateX = ((y - centerY) / centerY) * -3.5;
          const rotateY = ((x - centerX) / centerX) * 3.5;
          card.style.transform = `perspective(1200px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) translateY(-2px)`;
        }
      });

      card.addEventListener("mouseleave", () => {
        card.style.transform = "perspective(1200px) rotateX(0deg) rotateY(0deg) translateY(0)";
      });
    });
  }

  /* ==========================================================================
     7. 流式数字滚轮动效 (Smooth Odometer Rollers)
     ========================================================================== */
  initOdometerCounters() {
    const ids = ["statTotal", "statFormal", "statLegacy", "statDone"];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;

      let lastVal = 0;
      const observer = new MutationObserver(() => {
        const text = el.innerText.trim();
        const num = parseInt(text, 10);
        if (!isNaN(num) && num !== lastVal && !el.__isAnimating) {
          this.animateNumber(el, lastVal, num, 500);
          lastVal = num;
        }
      });
      observer.observe(el, { childList: true, characterData: true, subtree: true });
    });
  }

  animateNumber(el, start, end, duration) {
    el.__isAnimating = true;
    const startTime = performance.now();
    const update = (now) => {
      const elapsed = now - startTime;
      const progress = Math.min(1, elapsed / duration);
      const ease = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
      const current = Math.round(start + (end - start) * ease);
      el.textContent = current;
      if (progress < 1) {
        requestAnimationFrame(update);
      } else {
        el.textContent = end;
        el.__isAnimating = false;
      }
    };
    requestAnimationFrame(update);
  }

  initVisibilityListener() {
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        this.isPaused = true;
        if (this.animId) cancelAnimationFrame(this.animId);
      } else {
        this.isPaused = false;
        this.lastFrameTime = performance.now();
        this.render();
      }
    });
  }
}

// 自动安全实例化
if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    window.activeTheoryFX = new ActiveTheoryEngine();
  });
}
