/**
 * AnimeAutoSub Luminous Aurora & Multi-Sensory FX Engine (web/static/cyber-fx.js)
 * 2026/2027 Cutting-Edge Visual & Interactive Showcase:
 * 1. Fluid Aurora Plasma Wave Canvas (流动极光流体画布与鼠标水波引力涟漪)
 * 2. Prismatic Holographic 3D Tilt Cards (全息彩虹折射光芒与三维物理悬浮)
 * 3. Crystal Sparkle Click Explosions (微晶爆裂交互微粒子)
 * 4. Procedural Web Audio Synthesizer Haptics (原生纯微合成拟真触觉声效)
 * 5. Smooth Odometer Counter Animation (核心指标数字流式滚动)
 * 6. Dynamic Theme & Sound Control (支持 ☀️ 极光浅色 / 🌙 深空暗色 无缝切换，默认极光浅色)
 */

class CyberFXEngine {
  constructor() {
    this.canvas = null;
    this.ctx = null;
    this.width = 0;
    this.height = 0;
    this.time = 0;
    this.mouse = { x: -1000, y: -1000, targetX: -1000, targetY: -1000, down: false };
    this.sparkles = [];
    this.animId = null;
    this.isPaused = false;

    // 音频合成器状态
    this.audioCtx = null;
    this.soundEnabled = localStorage.getItem("aas_sound") !== "0";

    // 主题状态 (默认 100% 极光浅色)
    this.currentTheme = localStorage.getItem("aas_theme") || "light";

    this.initTheme();
    this.initCanvas();
    this.initAudioSynthesizer();
    this.initSparkleSystem();
    this.initCardInteractions();
    this.initOdometerCounters();
    this.initVisibilityListener();
    this.bindControls();
  }

  /* ==========================================================================
     1. 主题与声效状态管理 (默认极光亮色)
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
      themeBtn.title = theme === "dark" ? "当前: 深空暗色 (点击切换为极光浅色)" : "当前: 极光浅色 (点击切换为深空暗色)";
    }
  }

  toggleTheme() {
    const nextTheme = this.currentTheme === "dark" ? "light" : "dark";
    this.applyTheme(nextTheme);
    this.playHapticSound("toggle");
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
      soundBtn.title = this.soundEnabled ? "触觉按键音效: 已开启 (点击静音)" : "触觉按键音效: 已静音 (点击开启)";
    }
    if (this.soundEnabled) {
      this.playHapticSound("success");
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
     2. 纯原生 Web Audio 合成器 (0 音频文件，纯声波物理合成次世代声效)
     ========================================================================== */
  initAudioSynthesizer() {
    // 首次用户交互时安全激活 AudioContext
    const unlockAudio = () => {
      if (!this.audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (AudioContextClass) {
          this.audioCtx = new AudioContextClass();
        }
      }
      if (this.audioCtx && this.audioCtx.state === "suspended") {
        this.audioCtx.resume();
      }
      window.removeEventListener("pointerdown", unlockAudio);
    };
    window.addEventListener("pointerdown", unlockAudio, { passive: true });
  }

  playHapticSound(type = "tick") {
    if (!this.soundEnabled || !this.audioCtx) return;
    try {
      if (this.audioCtx.state === "suspended") {
        this.audioCtx.resume();
      }
      const now = this.audioCtx.currentTime;

      if (type === "tick") {
        // 轻盈拟真触觉微击 (800Hz -> 200Hz 40ms)
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(800, now);
        osc.frequency.exponentialRampToValueAtTime(180, now + 0.04);
        gain.gain.setValueAtTime(0.04, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.04);
        osc.connect(gain);
        gain.connect(this.audioCtx.destination);
        osc.start(now);
        osc.stop(now + 0.045);
      } else if (type === "pop" || type === "primary") {
        // 清脆微晶质感双音 (1200Hz / 1600Hz)
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.type = "triangle";
        osc.frequency.setValueAtTime(1400, now);
        osc.frequency.exponentialRampToValueAtTime(450, now + 0.07);
        gain.gain.setValueAtTime(0.06, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.07);
        osc.connect(gain);
        gain.connect(this.audioCtx.destination);
        osc.start(now);
        osc.stop(now + 0.08);
      } else if (type === "success") {
        // 水晶和弦泛音 (双音和弦 E6 -> B6)
        [1318.51, 1975.53].forEach((freq, idx) => {
          const osc = this.audioCtx.createOscillator();
          const gain = this.audioCtx.createGain();
          const startTime = now + idx * 0.06;
          osc.type = "sine";
          osc.frequency.setValueAtTime(freq, startTime);
          gain.gain.setValueAtTime(0.04, startTime);
          gain.gain.exponentialRampToValueAtTime(0.0001, startTime + 0.22);
          osc.connect(gain);
          gain.connect(this.audioCtx.destination);
          osc.start(startTime);
          osc.stop(startTime + 0.23);
        });
      } else if (type === "toggle") {
        // 模式切换微动弹响 (600Hz -> 900Hz)
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(550, now);
        osc.frequency.exponentialRampToValueAtTime(950, now + 0.06);
        gain.gain.setValueAtTime(0.045, now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.06);
        osc.connect(gain);
        gain.connect(this.audioCtx.destination);
        osc.start(now);
        osc.stop(now + 0.065);
      }
    } catch (_) {}
  }

  /* ==========================================================================
     3. 流体极光波浪 Canvas (Fluid Aurora Plasma Waves)
     ========================================================================== */
  initCanvas() {
    this.canvas = document.getElementById("cyberCanvas");
    if (!this.canvas) {
      this.canvas = document.createElement("canvas");
      this.canvas.id = "cyberCanvas";
      this.canvas.className = "cyber-canvas";
      document.body.prepend(this.canvas);
    }

    // 强内联样式兜底：确保绝对不脱离固定背景层
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
      this.mouse.targetX = e.clientX;
      this.mouse.targetY = e.clientY;
    }, { passive: true });

    window.addEventListener("mousedown", (e) => {
      this.mouse.down = true;
      this.spawnSparkles(e.clientX, e.clientY, 14);
    }, { passive: true });

    window.addEventListener("mouseup", () => {
      this.mouse.down = false;
    }, { passive: true });

    window.addEventListener("mouseout", () => {
      this.mouse.targetX = -1000;
      this.mouse.targetY = -1000;
    });

    this.render();
  }

  resizeCanvas() {
    if (!this.canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.width = window.innerWidth;
    this.height = window.innerHeight;
    this.canvas.width = this.width * dpr;
    this.canvas.height = this.height * dpr;
    this.ctx.scale(dpr, dpr);
  }

  render() {
    if (this.isPaused) return;

    this.time += 0.015;
    // 鼠标坐标弹簧平滑插值
    this.mouse.x += (this.mouse.targetX - this.mouse.x) * 0.12;
    this.mouse.y += (this.mouse.targetY - this.mouse.y) * 0.12;

    this.ctx.clearRect(0, 0, this.width, this.height);

    const isDark = document.body.classList.contains("dark-theme");

    // 绘制 4 层流体极光彩缎 (Fluid Aurora Ribbons)
    this.drawAuroraWaves(isDark);

    // 绘制微晶爆裂粒子系统
    this.drawSparkles();

    this.animId = requestAnimationFrame(() => this.render());
  }

  drawAuroraWaves(isDark) {
    const waves = isDark
      ? [
          { yRatio: 0.35, amp: 70, freq: 0.0022, speed: 0.8, color1: "rgba(0, 240, 255, 0.16)", color2: "rgba(168, 85, 247, 0.0)" },
          { yRatio: 0.55, amp: 90, freq: 0.0018, speed: -0.6, color1: "rgba(168, 85, 247, 0.14)", color2: "rgba(244, 63, 94, 0.0)" },
          { yRatio: 0.75, amp: 60, freq: 0.0026, speed: 0.7, color1: "rgba(0, 255, 136, 0.12)", color2: "rgba(0, 240, 255, 0.0)" },
          { yRatio: 0.90, amp: 80, freq: 0.0015, speed: -0.5, color1: "rgba(56, 189, 248, 0.15)", color2: "rgba(168, 85, 247, 0.0)" }
        ]
      : [
          // 极光亮色：高贵雅致的青瓷、鸢尾紫、樱粉、珊瑚金流光渐变
          { yRatio: 0.28, amp: 85, freq: 0.0020, speed: 0.9, color1: "rgba(79, 70, 229, 0.18)", color2: "rgba(14, 165, 233, 0.0)" },
          { yRatio: 0.48, amp: 105, freq: 0.0016, speed: -0.7, color1: "rgba(236, 72, 153, 0.15)", color2: "rgba(124, 58, 237, 0.0)" },
          { yRatio: 0.68, amp: 90, freq: 0.0024, speed: 0.8, color1: "rgba(14, 165, 233, 0.16)", color2: "rgba(16, 185, 129, 0.0)" },
          { yRatio: 0.88, amp: 110, freq: 0.0014, speed: -0.6, color1: "rgba(245, 158, 11, 0.13)", color2: "rgba(236, 72, 153, 0.0)" }
        ];

    const step = 28;
    waves.forEach((w, idx) => {
      this.ctx.beginPath();
      const baseY = this.height * w.yRatio;

      this.ctx.moveTo(0, this.height);
      this.ctx.lineTo(0, baseY);

      for (let x = 0; x <= this.width + step; x += step) {
        // 多谐波干涉正弦波合成
        let y = baseY +
          Math.sin(x * w.freq + this.time * w.speed) * w.amp +
          Math.cos(x * w.freq * 0.5 + this.time * w.speed * 0.7) * (w.amp * 0.45);

        // 鼠标涟漪与引力交互 (水波扰动)
        const dx = x - this.mouse.x;
        const dy = y - this.mouse.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 260) {
          const force = (1 - dist / 260);
          y += Math.sin(dist * 0.05 - this.time * 4) * 22 * force;
        }

        this.ctx.lineTo(x, y);
      }

      this.ctx.lineTo(this.width, this.height);
      this.ctx.closePath();

      // 垂直渐变填充
      const grad = this.ctx.createLinearGradient(0, baseY - w.amp, 0, baseY + w.amp * 1.5);
      grad.addColorStop(0, w.color1);
      grad.addColorStop(1, w.color2);
      this.ctx.fillStyle = grad;
      this.ctx.fill();
    });
  }

  /* ==========================================================================
     4. 微晶爆裂交互粒子系统 (Crystal Sparkles)
     ========================================================================== */
  initSparkleSystem() {
    // 监听全局交互按钮微点击爆裂
    document.addEventListener("click", (e) => {
      const target = e.target.closest("button, .btn, .filter-btn, .task-card");
      if (target) {
        const isPrimary = target.classList.contains("btn-primary") || target.id === "btnConfirmDeleteTask";
        this.spawnSparkles(e.clientX, e.clientY, isPrimary ? 20 : 10);
        this.playHapticSound(isPrimary ? "primary" : "tick");
      }
    });
  }

  spawnSparkles(x, y, count = 12) {
    const isDark = document.body.classList.contains("dark-theme");
    const colors = isDark
      ? ["#00f0ff", "#a855f7", "#00ff88", "#facc15", "#ffffff"]
      : ["#4f46e5", "#7c3aed", "#ec4899", "#0ea5e9", "#f59e0b", "#10b981"];

    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.6;
      const speed = Math.random() * 4.5 + 2.0;
      this.sparkles.push({
        x: x,
        y: y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 1.0,
        size: Math.random() * 3.5 + 2.0,
        color: colors[Math.floor(Math.random() * colors.length)],
        alpha: 1.0,
        decay: Math.random() * 0.025 + 0.02,
        rotation: Math.random() * Math.PI,
        rotSpeed: (Math.random() - 0.5) * 0.2
      });
    }
  }

  drawSparkles() {
    for (let i = this.sparkles.length - 1; i >= 0; i--) {
      const s = this.sparkles[i];
      s.x += s.vx;
      s.y += s.vy;
      s.vy += 0.12; // 微引力下坠
      s.vx *= 0.96;
      s.alpha -= s.decay;
      s.rotation += s.rotSpeed;

      if (s.alpha <= 0) {
        this.sparkles.splice(i, 1);
        continue;
      }

      this.ctx.save();
      this.ctx.translate(s.x, s.y);
      this.ctx.rotate(s.rotation);
      this.ctx.globalAlpha = Math.max(0, s.alpha);
      this.ctx.fillStyle = s.color;

      // 绘制闪耀四芒星微晶
      this.ctx.beginPath();
      const r = s.size;
      this.ctx.moveTo(0, -r);
      this.ctx.lineTo(r * 0.35, -r * 0.35);
      this.ctx.lineTo(r, 0);
      this.ctx.lineTo(r * 0.35, r * 0.35);
      this.ctx.lineTo(0, r);
      this.ctx.lineTo(-r * 0.35, r * 0.35);
      this.ctx.lineTo(-r, 0);
      this.ctx.lineTo(-r * 0.35, -r * 0.35);
      this.ctx.closePath();
      this.ctx.fill();

      this.ctx.restore();
    }
  }

  /* ==========================================================================
     5. 全息 3D 悬浮倾角与彩虹折射光芒 (3D Tilt & Holographic Rainbow Sheen)
     ========================================================================== */
  initCardInteractions() {
    this.attachCardEffects();

    const container = document.getElementById("tasksListContainer");
    if (container) {
      const observer = new MutationObserver(() => {
        this.attachCardEffects();
      });
      observer.observe(container, { childList: true, subtree: false });
    }
  }

  attachCardEffects() {
    const cards = document.querySelectorAll(".task-card, .stat-card, .modal-card");
    cards.forEach(card => {
      if (card.__cyberFxBound) return;
      card.__cyberFxBound = true;

      card.addEventListener("mousemove", (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        card.style.setProperty("--mouse-x", `${x}px`);
        card.style.setProperty("--mouse-y", `${y}px`);

        if (card.classList.contains("task-card") || card.classList.contains("stat-card")) {
          const centerX = rect.width / 2;
          const centerY = rect.height / 2;
          const rotateX = ((y - centerY) / centerY) * -4.5;
          const rotateY = ((x - centerX) / centerX) * 4.5;
          card.style.transform = `perspective(1000px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) translateY(-4px)`;
        }
      });

      card.addEventListener("mouseleave", () => {
        card.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg) translateY(0)";
      });
    });
  }

  /* ==========================================================================
     6. 核心指标流式数字滚动动画 (Smooth Odometer Numbers)
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
          this.animateNumber(el, lastVal, num, 600);
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
      // easeOutExpo 缓动曲线
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
        this.render();
      }
    });
  }
}

// 自动安全实例化
if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    window.cyberFX = new CyberFXEngine();
  });
}
