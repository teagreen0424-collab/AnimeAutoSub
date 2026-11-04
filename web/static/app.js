/**
 * AnimeAutoSub WebUI 前端核心逻辑 (web/static/app.js)
 * 原生 ES Modules，包含 P2 + P3 全套功能:
 * 1. 新建任务 (弹窗、服务器片源快捷选择、全局拖拽投放)
 * 2. 独占队列与排队位置展示
 * 3. 实时 SSE 进度流推送 (阶段百分比 + 加权总进度 + 实时滚屏日志)
 * 4. 3秒内安全取消与 GPU 租约释放
 * 5. 自动断点续跑 (跳过已完成阶段)
 * 6. 流水线跑完自动跳转详情并无缝播放成片
 * 7. P3: 调试任务过滤开关 (默认隐藏 test_ 任务，严禁批量删除)
 * 8. P3: 字幕编辑器 (每页 50 行分页、行内直接改字并标脏、保存并自动备份)
 * 9. P3: 单帧精确预览 (M1 规范: -i 精确 seek、≥150ms 节流、AbortController 取消前序请求、命中缓存 0ms)
 * 10. P3: 增量重渲染 (只跑排版与压制，跳过 OCR 和翻译，联动 SSE 动态跟踪)
 * 11. P3: 字幕与视频多格式导出 (ASS / SRT / 视频)
 */

class WebUIApp {
  constructor() {
    this.tasks = [];
    this.currentTask = null;
    this.currentFilter = "all";
    this.searchQuery = "";
    this.currentEventSource = null;

    // DOM 元素引用
    this.screenTaskList = document.getElementById("screenTaskList");
    this.screenTaskDetail = document.getElementById("screenTaskDetail");
    this.navTaskList = document.getElementById("navTaskList");
    this.detailNavSep = document.getElementById("detailNavSep");
    this.detailNavTitle = document.getElementById("detailNavTitle");
    this.btnBackToList = document.getElementById("btnBackToList");
    this.btnRefresh = document.getElementById("btnRefresh");
    this.btnNewTask = document.getElementById("btnNewTask");
    this.tasksListContainer = document.getElementById("tasksListContainer");

    // 统计指标
    this.statTotal = document.getElementById("statTotal");
    this.statFormal = document.getElementById("statFormal");
    this.statLegacy = document.getElementById("statLegacy");
    this.statDone = document.getElementById("statDone");

    // 过滤与搜索
    this.cntAll = document.getElementById("cntAll");
    this.cntFormal = document.getElementById("cntFormal");
    this.cntLegacy = document.getElementById("cntLegacy");
    this.taskSearchInput = document.getElementById("taskSearchInput");
    this.chkShowDebug = document.getElementById("chkShowDebug");
    this.showDebug = false;

    // 队列与 GPU 状态
    this.queueStatusBadge = document.getElementById("queueStatusBadge");
    this.queueDot = document.getElementById("queueDot");
    this.queueText = document.getElementById("queueText");
    this.gpuName = document.getElementById("gpuName");
    this.gpuMem = document.getElementById("gpuMem");
    this.gpuBar = document.getElementById("gpuBar");

    // 详情页元素
    this.detailTitle = document.getElementById("detailTitle");
    this.detailTags = document.getElementById("detailTags");
    this.detailStatusPill = document.getElementById("detailStatusPill");
    this.btnResumeTask = document.getElementById("btnResumeTask");
    this.btnCancelTask = document.getElementById("btnCancelTask");
    this.liveProgressPanel = document.getElementById("liveProgressPanel");
    this.liveStageTitle = document.getElementById("liveStageTitle");
    this.liveTotalPctText = document.getElementById("liveTotalPctText");
    this.liveTotalProgressBar = document.getElementById("liveTotalProgressBar");
    this.liveQueueMsg = document.getElementById("liveQueueMsg");
    this.liveHeartbeat = document.getElementById("liveHeartbeat");

    this.detailVideo = document.getElementById("detailVideo");
    this.videoFileName = document.getElementById("videoFileName");
    this.videoEmptyPlaceholder = document.getElementById("videoEmptyPlaceholder");
    this.productsTableBody = document.getElementById("productsTableBody");
    this.productsCount = document.getElementById("productsCount");
    this.pipelineTrack = document.getElementById("pipelineTrack");
    this.stagesSummary = document.getElementById("stagesSummary");
    this.logContent = document.getElementById("logContent");
    this.manifestContent = document.getElementById("manifestContent");
    this.chkAutoScroll = document.getElementById("chkAutoScroll");
    this.btnOpenSubtitleEditor = document.getElementById("btnOpenSubtitleEditor");

    // P3: 详情页字幕编辑器与单帧预览 DOM
    this.subtitlesTotalCount = document.getElementById("subtitlesTotalCount");
    this.subtitlesDirtyBadge = document.getElementById("subtitlesDirtyBadge");
    this.btnExportAss = document.getElementById("btnExportAss");
    this.btnExportSrt = document.getElementById("btnExportSrt");
    this.btnSaveSubtitles = document.getElementById("btnSaveSubtitles");
    this.btnRerender = document.getElementById("btnRerender");
    this.subtitlesTableBody = document.getElementById("subtitlesTableBody");
    this.paginationBar = document.getElementById("paginationBar");
    this.btnFirstPage = document.getElementById("btnFirstPage");
    this.btnPrevPage = document.getElementById("btnPrevPage");
    this.btnNextPage = document.getElementById("btnNextPage");
    this.btnLastPage = document.getElementById("btnLastPage");
    this.pageInfo = document.getElementById("pageInfo");
    this.previewTimeTag = document.getElementById("previewTimeTag");
    this.previewLoading = document.getElementById("previewLoading");
    this.previewImg = document.getElementById("previewImg");
    this.previewPlaceholder = document.getElementById("previewPlaceholder");

    // R1: 全屏独立字幕编辑器 (#screenEditor, 独立路由 #task=<id>&edit=1)
    this.screenEditor = document.getElementById("screenEditor");
    this.btnEditorBackToDetail = document.getElementById("btnEditorBackToDetail");
    this.editorTaskTitle = document.getElementById("editorTaskTitle");
    this.editorTaskTag = document.getElementById("editorTaskTag");
    this.fsSubtitlesCount = document.getElementById("fsSubtitlesCount");
    this.fsSubtitlesDirtyBadge = document.getElementById("fsSubtitlesDirtyBadge");
    this.fsBtnExportAss = document.getElementById("fsBtnExportAss");
    this.fsBtnExportSrt = document.getElementById("fsBtnExportSrt");
    this.fsBtnSaveSubtitles = document.getElementById("fsBtnSaveSubtitles");
    this.fsBtnRerender = document.getElementById("fsBtnRerender");
    this.fsPreviewTimeTag = document.getElementById("fsPreviewTimeTag");
    this.fsPreviewViewport = document.getElementById("fsPreviewViewport");
    this.fsPreviewLoading = document.getElementById("fsPreviewLoading");
    this.fsPreviewImg = document.getElementById("fsPreviewImg");
    this.fsPreviewPlaceholder = document.getElementById("fsPreviewPlaceholder");
    this.fsFrameNotice = document.getElementById("fsFrameNotice");
    this.fsFrameRenderCost = document.getElementById("fsFrameRenderCost");
    this.fsSubtitlesTableBody = document.getElementById("fsSubtitlesTableBody");
    this.fsPaginationBar = document.getElementById("fsPaginationBar");
    this.fsBtnFirstPage = document.getElementById("fsBtnFirstPage");
    this.fsBtnPrevPage = document.getElementById("fsBtnPrevPage");
    this.fsPageInfo = document.getElementById("fsPageInfo");
    this.fsBtnNextPage = document.getElementById("fsBtnNextPage");
    this.fsBtnLastPage = document.getElementById("fsBtnLastPage");

    // S2: 成片下载与快捷导出 DOM
    this.btnDetailDownloadVideo = document.getElementById("btnDetailDownloadVideo");
    this.btnVideoCardDownload = document.getElementById("btnVideoCardDownload");
    this.fsBtnDownloadVideoTop = document.getElementById("fsBtnDownloadVideoTop");
    this.fsBtnDownloadVideoBottom = document.getElementById("fsBtnDownloadVideoBottom");
    this.fsBtnDownloadAssBottom = document.getElementById("fsBtnDownloadAssBottom");
    this.fsBtnDownloadSrtBottom = document.getElementById("fsBtnDownloadSrtBottom");
    this.fsVideoStatus = document.getElementById("fsVideoStatus");

    // S2: 系统设置屏幕与网络异常 DOM
    this.btnSettings = document.getElementById("btnSettings");
    this.offlineBanner = document.getElementById("offlineBanner");
    this.btnRetryOffline = document.getElementById("btnRetryOffline");
    this.screenSettings = document.getElementById("screenSettings");
    this.btnSettingsBackToList = document.getElementById("btnSettingsBackToList");
    this.chkSettingsShowDebug = document.getElementById("chkSettingsShowDebug");
    this.cfgPort = document.getElementById("cfgPort");
    this.cfgOllamaUrl = document.getElementById("cfgOllamaUrl");
    this.cfgModelsPath = document.getElementById("cfgModelsPath");
    this.cfgTranslationModel = document.getElementById("cfgTranslationModel");
    this.cfgOcrEngine = document.getElementById("cfgOcrEngine");
    this.cfgFfmpegPath = document.getElementById("cfgFfmpegPath");
    this.cfgSchemaVersion = document.getElementById("cfgSchemaVersion");

    // P3: 字幕数据状态
    this.subtitlesData = [];
    this.originalSubtitlesJson = "[]";
    this.currentSubPage = 1;
    this.pageSize = 50;
    this.isSubtitlesDirty = false;
    this.selectedSubtitleIdx = -1;
    this.previewThrottleTimer = null;
    this.previewAbortController = null;

    // 新建任务弹窗与拖拽
    this.modalNewTask = document.getElementById("modalNewTask");
    this.modalCloseBtn = document.getElementById("modalCloseBtn");
    this.btnCancelModal = document.getElementById("btnCancelModal");
    this.formNewTask = document.getElementById("formNewTask");
    this.selectQuickFile = document.getElementById("selectQuickFile");
    this.inputVideoPath = document.getElementById("inputVideoPath");
    this.selectLang = document.getElementById("selectLang");
    this.selectMode = document.getElementById("selectMode");
    this.inputTaskTitle = document.getElementById("inputTaskTitle");
    this.selectEngine = document.getElementById("selectEngine");
    this.engineCostEstimateRow = document.getElementById("engineCostEstimateRow");
    this.engineCostEstimateText = document.getElementById("engineCostEstimateText");
    this.settingsEnginesTableBody = document.getElementById("settingsEnginesTableBody");
    this.availableEngines = [];
    this.dragDropOverlay = document.getElementById("dragDropOverlay");
    this.uploadProgressContainer = document.getElementById("uploadProgressContainer");
    this.uploadStatusText = document.getElementById("uploadStatusText");
    this.uploadPercentText = document.getElementById("uploadPercentText");
    this.uploadProgressBar = document.getElementById("uploadProgressBar");

    this.initEventListeners();
    this.loadTasks().then(() => {
      this.handleHashChange();
    });
    this.loadGpuStatus();

    // 监听 Hash 变化
    window.addEventListener("hashchange", () => this.handleHashChange());

    // 定时轮询 GPU 与队列状态
    setInterval(() => this.loadGpuStatus(), 4000);
  }

  initEventListeners() {
    // 导航与页面切换
    if (this.navTaskList) this.navTaskList.addEventListener("click", () => this.showScreen("list"));
    if (this.btnBackToList) this.btnBackToList.addEventListener("click", () => this.showScreen("list"));
    this.btnRefresh.addEventListener("click", () => {
      this.loadTasks();
      this.loadGpuStatus();
    });

    // 筛选过滤
    document.querySelectorAll(".filter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        this.currentFilter = btn.dataset.filter;
        this.renderTaskList();
      });
    });

    // 调试任务切换
    if (this.chkShowDebug) {
      this.chkShowDebug.addEventListener("change", (e) => {
        this.showDebug = e.target.checked;
        this.updateStats();
        this.renderTaskList();
      });
    }

    // 搜索过滤
    this.taskSearchInput.addEventListener("input", (e) => {
      this.searchQuery = e.target.value.trim().toLowerCase();
      this.renderTaskList();
    });

    // 详情页 Tabs 切换
    document.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        const tabKey = btn.dataset.tab;
        if (tabKey === "log") document.getElementById("tabPanelLog").classList.add("active");
        if (tabKey === "manifest") document.getElementById("tabPanelManifest").classList.add("active");
        if (tabKey === "subtitles") {
          document.getElementById("tabPanelSubtitles").classList.add("active");
          if (this.currentTask) {
            this.loadSubtitles(this.currentTask.task_id);
          }
        }
      });
    });

    // R1 规范: 详情顶栏"编辑字幕"按钮直接导航到独立全屏视图 (#task=<id>&edit=1)
    if (this.btnOpenSubtitleEditor) {
      this.btnOpenSubtitleEditor.addEventListener("click", () => {
        if (this.currentTask) {
          window.location.hash = `#task=${this.currentTask.task_id}&edit=1`;
        }
      });
    }

    // R1 规范: 全屏编辑器顶栏"← 返回任务详情"按钮
    if (this.btnEditorBackToDetail) {
      this.btnEditorBackToDetail.addEventListener("click", () => {
        if (this.currentTask) {
          window.location.hash = `#task=${this.currentTask.task_id}`;
        } else {
          this.showScreen("list");
        }
      });
    }

    // P3: 分页按钮控制 (详情页 Tab)
    if (this.btnFirstPage) {
      this.btnFirstPage.addEventListener("click", () => {
        if (this.currentSubPage > 1) {
          this.currentSubPage = 1;
          this.renderSubtitlesPage();
        }
      });
    }
    if (this.btnPrevPage) {
      this.btnPrevPage.addEventListener("click", () => {
        if (this.currentSubPage > 1) {
          this.currentSubPage--;
          this.renderSubtitlesPage();
        }
      });
    }
    if (this.btnNextPage) {
      this.btnNextPage.addEventListener("click", () => {
        const maxPage = Math.max(1, Math.ceil(this.subtitlesData.length / this.pageSize));
        if (this.currentSubPage < maxPage) {
          this.currentSubPage++;
          this.renderSubtitlesPage();
        }
      });
    }
    if (this.btnLastPage) {
      this.btnLastPage.addEventListener("click", () => {
        const maxPage = Math.max(1, Math.ceil(this.subtitlesData.length / this.pageSize));
        if (this.currentSubPage < maxPage) {
          this.currentSubPage = maxPage;
          this.renderSubtitlesPage();
        }
      });
    }

    // R1: 全屏编辑器分页按钮控制
    if (this.fsBtnFirstPage) {
      this.fsBtnFirstPage.addEventListener("click", () => {
        if (this.currentSubPage > 1) {
          this.currentSubPage = 1;
          this.renderSubtitlesPage();
        }
      });
    }
    if (this.fsBtnPrevPage) {
      this.fsBtnPrevPage.addEventListener("click", () => {
        if (this.currentSubPage > 1) {
          this.currentSubPage--;
          this.renderSubtitlesPage();
        }
      });
    }
    if (this.fsBtnNextPage) {
      this.fsBtnNextPage.addEventListener("click", () => {
        const maxPage = Math.max(1, Math.ceil(this.subtitlesData.length / this.pageSize));
        if (this.currentSubPage < maxPage) {
          this.currentSubPage++;
          this.renderSubtitlesPage();
        }
      });
    }
    if (this.fsBtnLastPage) {
      this.fsBtnLastPage.addEventListener("click", () => {
        const maxPage = Math.max(1, Math.ceil(this.subtitlesData.length / this.pageSize));
        if (this.currentSubPage < maxPage) {
          this.currentSubPage = maxPage;
          this.renderSubtitlesPage();
        }
      });
    }

    // P3: 保存修改 (详情 Tab 与全屏工作台双向响应)
    if (this.btnSaveSubtitles) {
      this.btnSaveSubtitles.addEventListener("click", () => this.saveSubtitles());
    }
    if (this.fsBtnSaveSubtitles) {
      this.fsBtnSaveSubtitles.addEventListener("click", () => this.saveSubtitles());
    }

    // P3: 增量重渲染 (详情 Tab 与全屏工作台双向响应)
    if (this.btnRerender) {
      this.btnRerender.addEventListener("click", () => this.rerenderCurrentTask());
    }
    if (this.fsBtnRerender) {
      this.fsBtnRerender.addEventListener("click", () => this.rerenderCurrentTask());
    }

    // P3: 导出
    if (this.btnExportAss) {
      this.btnExportAss.addEventListener("click", () => {
        if (this.currentTask) window.open(`/api/tasks/${this.currentTask.task_id}/export/ass`, "_blank");
      });
    }
    if (this.fsBtnExportAss) {
      this.fsBtnExportAss.addEventListener("click", () => {
        if (this.currentTask) window.open(`/api/tasks/${this.currentTask.task_id}/export/ass`, "_blank");
      });
    }
    if (this.btnExportSrt) {
      this.btnExportSrt.addEventListener("click", () => {
        if (this.currentTask) window.open(`/api/tasks/${this.currentTask.task_id}/export/srt`, "_blank");
      });
    }
    if (this.fsBtnExportSrt) {
      this.fsBtnExportSrt.addEventListener("click", () => {
        if (this.currentTask) window.open(`/api/tasks/${this.currentTask.task_id}/export/srt`, "_blank");
      });
    }

    // S2: 成片下载与快捷导出监听
    const triggerVideoDownload = () => {
      if (this.currentTask) {
        window.open(`/api/tasks/${this.currentTask.task_id}/export/video`, "_blank");
      }
    };
    if (this.btnDetailDownloadVideo) this.btnDetailDownloadVideo.addEventListener("click", triggerVideoDownload);
    if (this.btnVideoCardDownload) this.btnVideoCardDownload.addEventListener("click", triggerVideoDownload);
    if (this.fsBtnDownloadVideoTop) this.fsBtnDownloadVideoTop.addEventListener("click", triggerVideoDownload);
    if (this.fsBtnDownloadVideoBottom) this.fsBtnDownloadVideoBottom.addEventListener("click", triggerVideoDownload);
    if (this.fsBtnDownloadAssBottom) {
      this.fsBtnDownloadAssBottom.addEventListener("click", () => {
        if (this.currentTask) window.open(`/api/tasks/${this.currentTask.task_id}/export/ass`, "_blank");
      });
    }
    if (this.fsBtnDownloadSrtBottom) {
      this.fsBtnDownloadSrtBottom.addEventListener("click", () => {
        if (this.currentTask) window.open(`/api/tasks/${this.currentTask.task_id}/export/srt`, "_blank");
      });
    }

    // S2: 设置页与离线重试监听
    if (this.btnSettings) {
      this.btnSettings.addEventListener("click", () => {
        window.location.hash = "#settings";
      });
    }
    if (this.btnSettingsBackToList) {
      this.btnSettingsBackToList.addEventListener("click", () => {
        this.showScreen("list");
      });
    }
    if (this.chkSettingsShowDebug) {
      this.chkSettingsShowDebug.addEventListener("change", (e) => {
        this.showDebug = e.target.checked;
        if (this.chkShowDebug) this.chkShowDebug.checked = this.showDebug;
        this.updateStats();
        this.renderTaskList();
      });
    }
    if (this.btnRetryOffline) {
      this.btnRetryOffline.addEventListener("click", () => {
        this.loadTasks();
        this.loadGpuStatus();
      });
    }

    // 新建任务弹窗事件
    this.btnNewTask.addEventListener("click", () => this.openNewTaskModal());
    this.modalCloseBtn.addEventListener("click", () => this.closeNewTaskModal());
    this.btnCancelModal.addEventListener("click", () => this.closeNewTaskModal());

    // 快捷选择片源联动
    this.selectQuickFile.addEventListener("change", (e) => {
      const val = e.target.value;
      if (val) {
        this.inputVideoPath.value = val;
        const filename = val.split("/").pop();
        this.inputTaskTitle.value = filename.substring(0, filename.lastIndexOf('.')) || filename;
        if (val.endsWith(".mp3") || val.endsWith(".wav") || val.includes("asr")) {
          this.selectMode.value = "asr";
        } else {
          this.selectMode.value = "ocr";
        }
        if (val.includes("ko") || val.includes("korean")) {
          this.selectLang.value = "ko";
        }
      }
    });

    // 提交新建任务
    this.formNewTask.addEventListener("submit", (e) => {
      e.preventDefault();
      this.submitNewTask();
    });

    // 全局拖拽支持
    window.addEventListener("dragenter", (e) => {
      e.preventDefault();
      this.dragDropOverlay.style.display = "flex";
    });
    window.addEventListener("dragover", (e) => e.preventDefault());
    this.dragDropOverlay.addEventListener("dragleave", (e) => {
      if (e.target === this.dragDropOverlay) {
        this.dragDropOverlay.style.display = "none";
      }
    });
    window.addEventListener("drop", (e) => {
      e.preventDefault();
      this.dragDropOverlay.style.display = "none";
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        const file = e.dataTransfer.files[0];
        this.handleFileDrop(file);
      }
    });

    // 翻译引擎选择切换预估费用显示
    if (this.selectEngine) {
      this.selectEngine.addEventListener("change", () => this.onEngineChange());
    }

    // 断点续跑与取消操作
    this.btnResumeTask.addEventListener("click", () => this.resumeCurrentTask());
    this.btnCancelTask.addEventListener("click", () => this.cancelCurrentTask());
  }

  handleHashChange() {
    const hash = window.location.hash;
    if (hash === "#modal=new") {
      this.showScreen("list");
      this.openNewTaskModal("ocr_input/test_3min.mp4");
    } else if (hash === "#settings") {
      this.showScreen("settings");
      this.loadSettings();
    } else if (hash.startsWith("#task=")) {
      const raw = hash.replace("#task=", "").trim();
      let taskId = raw;
      let isEdit = false;
      if (raw.includes("&")) {
        const parts = raw.split("&");
        taskId = parts[0];
        for (let p of parts.slice(1)) {
          if (p === "edit=1") isEdit = true;
        }
      }
      if (taskId) {
        if (isEdit) {
          this.openEditor(taskId);
        } else {
          this.openTaskDetail(taskId);
        }
      }
    } else {
      this.showScreen("list");
    }
  }

  // 退出原生全屏（浏览器返回键/鼠标侧键切屏时必须调用，否则全屏状态会残留到下一个页面）
  exitNativeFullscreen() {
    try {
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      } else if (document.webkitFullscreenElement && document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      }
    } catch (e) { /* 忽略 */ }
  }

  showScreen(screenName) {
    // 切屏前：退出全屏 + 暂停所有视频
    this.exitNativeFullscreen();
    document.querySelectorAll("video").forEach(v => { try { v.pause(); } catch (e) {} });

    if (screenName === "list") {
      this.stopSSE();
      if (window.location.hash) {
        history.pushState("", document.title, window.location.pathname + window.location.search);
      }
      if (this.screenTaskList) this.screenTaskList.style.display = "block";
      if (this.screenTaskDetail) this.screenTaskDetail.style.display = "none";
      if (this.screenEditor) this.screenEditor.style.display = "none";
      if (this.screenSettings) this.screenSettings.style.display = "none";
      if (this.navTaskList) this.navTaskList.classList.add("active");
      if (this.detailNavSep) this.detailNavSep.style.display = "none";
      if (this.detailNavTitle) this.detailNavTitle.style.display = "none";
      if (this.detailVideo) {
        this.detailVideo.pause();
      }
    } else if (screenName === "detail") {
      if (this.screenTaskList) this.screenTaskList.style.display = "none";
      if (this.screenTaskDetail) this.screenTaskDetail.style.display = "block";
      if (this.screenEditor) this.screenEditor.style.display = "none";
      if (this.screenSettings) this.screenSettings.style.display = "none";
      if (this.navTaskList) this.navTaskList.classList.remove("active");
      if (this.detailNavSep) this.detailNavSep.style.display = "inline";
      if (this.detailNavTitle) {
        this.detailNavTitle.style.display = "inline";
        if (this.currentTask) {
          this.detailNavTitle.textContent = this.currentTask.title;
        }
      }
      if (this.currentTask) {
        const targetHash = `#task=${this.currentTask.task_id}`;
        if (window.location.hash !== targetHash && !window.location.hash.includes("&edit=1")) {
          window.location.hash = targetHash;
        }
      }
    } else if (screenName === "editor") {
      if (this.screenTaskList) this.screenTaskList.style.display = "none";
      if (this.screenTaskDetail) this.screenTaskDetail.style.display = "none";
      if (this.screenEditor) this.screenEditor.style.display = "block";
      if (this.screenSettings) this.screenSettings.style.display = "none";
      if (this.navTaskList) this.navTaskList.classList.remove("active");
      if (this.detailNavSep) this.detailNavSep.style.display = "inline";
      if (this.detailNavTitle) {
        this.detailNavTitle.style.display = "inline";
        if (this.currentTask) {
          this.detailNavTitle.textContent = `${this.currentTask.title} (字幕编辑)`;
        }
      }
      if (this.detailVideo) {
        this.detailVideo.pause();
      }
      if (this.currentTask) {
        const targetHash = `#task=${this.currentTask.task_id}&edit=1`;
        if (window.location.hash !== targetHash) {
          window.location.hash = targetHash;
        }
      }
    } else if (screenName === "settings") {
      this.stopSSE();
      if (this.screenTaskList) this.screenTaskList.style.display = "none";
      if (this.screenTaskDetail) this.screenTaskDetail.style.display = "none";
      if (this.screenEditor) this.screenEditor.style.display = "none";
      if (this.screenSettings) this.screenSettings.style.display = "block";
      if (this.navTaskList) this.navTaskList.classList.remove("active");
      if (this.detailNavSep) this.detailNavSep.style.display = "inline";
      if (this.detailNavTitle) {
        this.detailNavTitle.style.display = "inline";
        this.detailNavTitle.textContent = "系统设置";
      }
      if (this.detailVideo) {
        this.detailVideo.pause();
      }
      if (window.location.hash !== "#settings") {
        window.location.hash = "#settings";
      }
    }
  }

  async loadSettings() {
    if (this.chkSettingsShowDebug) {
      this.chkSettingsShowDebug.checked = this.showDebug;
    }
    try {
      const resp = await fetch("/api/system/settings");
      const res = await resp.json();
      if (res.code === 0 && res.data) {
        const d = res.data;
        if (this.cfgPort) this.cfgPort.textContent = `${d.port} (${d.host})`;
        if (this.cfgOllamaUrl) this.cfgOllamaUrl.textContent = d.ollama_url;
        if (this.cfgModelsPath) this.cfgModelsPath.textContent = d.ollama_models_path;
        if (this.cfgTranslationModel) this.cfgTranslationModel.textContent = d.translation_model;
        if (this.cfgOcrEngine) this.cfgOcrEngine.textContent = d.ocr_engine;
        if (this.cfgFfmpegPath) this.cfgFfmpegPath.textContent = d.ffmpeg_path;
        if (this.cfgSchemaVersion) this.cfgSchemaVersion.textContent = `Schema v${d.schema_version}`;

        if (this.settingsEnginesTableBody && Array.isArray(d.engines)) {
          this.settingsEnginesTableBody.innerHTML = d.engines.map(e => {
            const keyPill = e.type === "api"
              ? (e.configured ? `<span style="color:#10b981;">✓ ${escapeHtml(e.masked_key)}</span>` : `<span style="color:#ef4444;">✗ 未配置</span>`)
              : `<span style="color:#94a3b8;">免密 (本地离线)</span>`;
            const pricingStr = e.type === "api"
              ? `入 ￥${e.pricing.input_per_m || 0} / 出 ￥${e.pricing.output_per_m || 0} ${e.pricing.currency || 'CNY'}`
              : `免费 (本地 GPU 显存)`;
            return `<tr>
              <td><code>${escapeHtml(e.id)}</code></td>
              <td style="font-weight: 500;">${escapeHtml(e.name)}</td>
              <td><span class="tag-badge ${e.type === 'api' ? 'tag-formal' : 'tag-mode'}">${e.type.toUpperCase()}</span></td>
              <td><code>${escapeHtml(e.model_name)}</code></td>
              <td>${keyPill}</td>
              <td style="font-size: 12px; color: #38bdf8;">${pricingStr}</td>
              <td style="font-size: 12px; color: #94a3b8;">${escapeHtml(e.description || '-')}</td>
            </tr>`;
          }).join("");
        }
      }
    } catch (e) {
      console.warn("加载系统设置失败:", e);
    }
  }

  async openEditor(taskId) {
    try {
      if (!this.currentTask || this.currentTask.task_id !== taskId) {
        const resp = await fetch(`/api/tasks/${taskId}`);
        const res = await resp.json();
        if (res.code !== 0) {
          alert("获取任务详情失败: " + res.message);
          return;
        }
        this.currentTask = res.data;
      }
      const task = this.currentTask;
      if (this.editorTaskTitle) {
        // S1-a: 省略中间长路径只显示任务名或简短标题，支持鼠标 hover 提示完整路径
        const shortTitle = (task.title || task.task_id).replace(/^.*[\\\/]/, '');
        this.editorTaskTitle.textContent = shortTitle;
        this.editorTaskTitle.title = task.title;
      }
      if (this.editorTaskTag) {
        const langName = task.lang === "ko" ? "KO" : "JA";
        const modeName = task.mode === "asr" ? "ASR" : "OCR";
        this.editorTaskTag.textContent = `${task.task_id} · ${langName} · ${modeName}`;
      }

      // S2 成片下载状态更新
      if (this.fsVideoStatus) {
        this.fsVideoStatus.textContent = task.has_video ? `🎬 ${task.video_name} (已就绪)` : `⏳ 尚未生成成片视频`;
      }
      if (this.fsBtnDownloadVideoTop) {
        this.fsBtnDownloadVideoTop.style.display = task.has_video ? "inline-flex" : "none";
      }
      if (this.fsBtnDownloadVideoBottom) {
        this.fsBtnDownloadVideoBottom.disabled = !task.has_video;
      }

      this.showScreen("editor");
      await this.loadSubtitles(taskId, true);
    } catch (e) {
      alert("进入字幕编辑器异常: " + e.message);
    }
  }

  async loadTasks() {
    try {
      const resp = await fetch("/api/tasks");
      const res = await resp.json();
      if (res.code === 0) {
        this.tasks = res.data.tasks || [];
        if (this.offlineBanner) this.offlineBanner.style.display = "none";
        this.updateStats(false);
        this.renderTaskList();
      } else {
        throw new Error(res.message || "接口返回错误");
      }
    } catch (err) {
      if (this.offlineBanner) this.offlineBanner.style.display = "flex";
      this.updateStats(true);
      this.tasksListContainer.innerHTML = `
        <div class="empty-state-wrap">
          <div class="empty-state-icon">⚠️</div>
          <div class="empty-state-title">无法加载任务列表</div>
          <div class="empty-state-desc">无法连接到本地服务 (${err.message})，请确认后端进程正常运行。</div>
          <button class="btn btn-outline btn-sm" onclick="window.app.loadTasks()">🔄 重新尝试连接</button>
        </div>
      `;
    }
  }

  async loadGpuStatus() {
    try {
      const resp = await fetch("/api/system/gpu");
      const res = await resp.json();
      if (res.code === 0) {
        const d = res.data;
        if (d.available) {
          this.gpuName.textContent = d.name;
          const usedG = (d.vram_used_mb / 1024).toFixed(1);
          const totalG = (d.vram_total_mb / 1024).toFixed(1);
          this.gpuMem.textContent = `${usedG}G / ${totalG}G (${d.utilization_percent}%)`;
          this.gpuBar.style.width = `${Math.min(100, Math.round((d.vram_used_mb / d.vram_total_mb) * 100))}%`;
        }
        
        // 队列状态更新
        const qLen = d.queue_length || 0;
        const activeId = d.active_task_id;
        if (activeId) {
          this.queueDot.className = "queue-dot busy";
          this.queueText.textContent = `执行中 (排队 ${qLen} 个)`;
        } else if (qLen > 0) {
          this.queueDot.className = "queue-dot busy";
          this.queueText.textContent = `排队中 (${qLen} 个待处理)`;
        } else {
          this.queueDot.className = "queue-dot";
          this.queueText.textContent = `队列: 空闲就绪`;
        }
      }
    } catch (e) {
      // 忽略短暂失败
    }
  }

  updateStats(isError = false) {
    if (isError) {
      const errTag = `<span class="stat-err" title="数据加载失败，服务离线">离线 ⚠</span>`;
      this.statTotal.innerHTML = errTag;
      this.statFormal.innerHTML = errTag;
      this.statLegacy.innerHTML = errTag;
      this.statDone.innerHTML = errTag;
      this.cntAll.textContent = "--";
      this.cntFormal.textContent = "--";
      this.cntLegacy.textContent = "--";
      return;
    }

    const visibleTasks = this.tasks.filter(t => this.showDebug || !t.is_debug);
    const total = visibleTasks.length;
    const formal = visibleTasks.filter(t => !t.is_legacy).length;
    const legacy = visibleTasks.filter(t => t.is_legacy).length;
    const done = visibleTasks.filter(t => t.has_video).length;

    this.statTotal.textContent = total;
    this.statFormal.textContent = formal;
    this.statLegacy.textContent = legacy;
    this.statDone.textContent = done;

    this.cntAll.textContent = total;
    this.cntFormal.textContent = formal;
    this.cntLegacy.textContent = legacy;
  }

  renderTaskList() {
    let filtered = this.tasks.slice();

    // 默认隐藏调试任务
    if (!this.showDebug) {
      filtered = filtered.filter(t => !t.is_debug);
    }

    if (this.currentFilter === "formal") {
      filtered = filtered.filter(t => !t.is_legacy);
    } else if (this.currentFilter === "legacy") {
      filtered = filtered.filter(t => t.is_legacy);
    }

    if (this.searchQuery) {
      filtered = filtered.filter(t => 
        t.title.toLowerCase().includes(this.searchQuery) ||
        t.task_id.toLowerCase().includes(this.searchQuery)
      );
    }

    if (filtered.length === 0) {
      if (this.tasks.length === 0) {
        this.tasksListContainer.innerHTML = `
          <div class="empty-state-wrap">
            <div class="empty-state-icon">🎬</div>
            <div class="empty-state-title">暂无视频翻译压制任务</div>
            <div class="empty-state-desc">点击右上角「+ 新建任务」或直接将视频拖入页面任意位置即可开始。</div>
            <button class="btn btn-primary" onclick="window.app.openNewTaskModal()">✨ 立即创建第一个任务</button>
          </div>
        `;
      } else {
        this.tasksListContainer.innerHTML = `
          <div class="empty-state-wrap">
            <div class="empty-state-icon">🔍</div>
            <div class="empty-state-title">未找到匹配的任务</div>
            <div class="empty-state-desc">当前关键词或过滤条件下没有任务，请尝试重置筛选或搜索。</div>
            <button class="btn btn-secondary btn-sm" onclick="window.app.resetFilters()">清空搜索与筛选</button>
          </div>
        `;
      }
      return;
    }

    this.tasksListContainer.innerHTML = filtered.map(task => {
      const formalTag = task.is_legacy 
        ? `<span class="tag-badge tag-legacy">历史产物 (只读)</span>` 
        : `<span class="tag-badge tag-formal">正式任务 (可续跑)</span>`;

      const debugTag = task.is_debug ? `<span class="tag-badge tag-debug">调试任务</span>` : "";

      const langTag = task.lang === "ko" 
        ? `<span class="tag-badge tag-lang-ko">韩文 (KO)</span>` 
        : `<span class="tag-badge tag-lang-ja">日文 (JA)</span>`;

      const modeTag = task.mode === "asr"
        ? `<span class="tag-badge tag-mode">语音识别 (ASR)</span>`
        : `<span class="tag-badge tag-mode">硬字幕提取 (OCR)</span>`;

      let statusBadge = `<span class="status-pill status-${task.status}">${task.status}</span>`;
      if (task.waiting_gpu) {
        statusBadge = `<span class="status-pill status-waiting_gpu">等待 GPU</span>`;
      } else if (task.status === "running") {
        statusBadge = `<span class="status-pill status-running">RUNNING (${task.total_pct || 0}%)</span>`;
      } else if (task.status === "queued" && task.queue_position > 0) {
        statusBadge = `<span class="status-pill status-queued">排队第 ${task.queue_position} 位</span>`;
      } else if (task.status === "failed") {
        statusBadge = `<span class="status-pill status-failed">执行失败 ✕</span>`;
      } else if (task.status === "interrupted") {
        statusBadge = `<span class="status-pill status-interrupted" style="background:rgba(245,158,11,0.18);color:#f59e0b;border:1px solid rgba(245,158,11,0.35);">⏸ 中断</span>`;
      }

      // 四颗按钮的可用性判定 (E2 规范: 不可用的置灰 disabled，不隐藏)
      const canDownload = Boolean(task.has_video);
      const canEditSubtitles = Boolean(task.has_subtitles || !task.is_legacy);
      const canResume = Boolean(!task.is_legacy && task.status !== "done" && task.status !== "running" && (task.can_resume || task.status === "failed" || task.status === "canceled" || task.status === "interrupted"));
      const canRerender = Boolean(!task.is_legacy && task.status !== "running" && (task.has_video || task.has_subtitles || task.status === "done"));

      const videoIndicator = task.has_video 
        ? `<span class="task-has-video">🎬 成片已就绪 (${escapeHtml(task.video_name)})</span>` 
        : `<span>⏳ 进度: ${task.total_pct || 0}%</span>`;

      return `
        <div class="task-card" data-task-id="${escapeHtml(task.task_id)}">
          <div class="task-card-header task-card__header">
            <div class="task-card-title-wrap task-card__title-wrap">
              <div class="task-card-title task-card__title" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</div>
              <div class="task-card-id task-card__id" title="${escapeHtml(task.task_id)}">${escapeHtml(task.task_id)}</div>
            </div>
            <div class="task-card-status-wrap">
              ${statusBadge}
            </div>
          </div>

          <div class="task-meta-tags">
            ${formalTag}
            ${debugTag}
            ${langTag}
            ${modeTag}
          </div>

          <div class="task-card-footer">
            ${videoIndicator}
            <span>${task.updated_at ? task.updated_at.substring(0, 19).replace("T", " ") : "-"}</span>
          </div>

          <div class="task-card-actions task-card__actions">
            <button class="btn btn-outline btn-xs btn-card-download" 
                    data-task-id="${escapeHtml(task.task_id)}" 
                    title="${canDownload ? '点击下载成片 (output.mp4)' : '尚未生成成片视频'}"
                    ${canDownload ? '' : 'disabled'}>
              下载成片
            </button>
            <button class="btn btn-outline btn-xs btn-card-subtitles" 
                    data-task-id="${escapeHtml(task.task_id)}" 
                    title="${canEditSubtitles ? '进入全屏字幕编辑器' : '无可用字幕数据'}"
                    ${canEditSubtitles ? '' : 'disabled'}>
              编辑字幕
            </button>
            <button class="btn btn-outline btn-xs btn-card-resume" 
                    data-task-id="${escapeHtml(task.task_id)}" 
                    title="${canResume ? '从断点恢复续跑' : (task.status === 'done' ? '任务已完成' : (task.status === 'running' ? '正在执行中' : '不可恢复'))}"
                    ${canResume ? '' : 'disabled'}>
              恢复
            </button>
            <button class="btn btn-outline btn-xs btn-card-rerender" 
                    data-task-id="${escapeHtml(task.task_id)}" 
                    title="${canRerender ? '跳过识别与翻译，增量重渲染' : (task.is_legacy ? '历史产物不支持重渲染' : '不可重渲染')}"
                    ${canRerender ? '' : 'disabled'}>
              重渲染
            </button>
          </div>
        </div>
      `;
    }).join("");

    this.tasksListContainer.querySelectorAll(".task-card").forEach(card => {
      card.addEventListener("click", () => {
        const taskId = card.dataset.taskId;
        this.openTaskDetail(taskId);
      });
    });

    this.tasksListContainer.querySelectorAll(".btn-card-download").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (btn.disabled) return;
        const taskId = btn.dataset.taskId;
        window.open(`/api/tasks/${taskId}/export/video`, "_blank");
      });
    });

    this.tasksListContainer.querySelectorAll(".btn-card-subtitles").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (btn.disabled) return;
        const taskId = btn.dataset.taskId;
        window.location.hash = `#task=${taskId}&edit=1`;
      });
    });

    this.tasksListContainer.querySelectorAll(".btn-card-resume").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (btn.disabled) return;
        const taskId = btn.dataset.taskId;
        this.openTaskDetail(taskId).then(() => {
          this.resumeCurrentTask();
        });
      });
    });

    this.tasksListContainer.querySelectorAll(".btn-card-rerender").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (btn.disabled) return;
        const taskId = btn.dataset.taskId;
        this.openTaskDetail(taskId).then(() => {
          this.rerenderCurrentTask();
        });
      });
    });
  }

  resetFilters() {
    this.searchQuery = "";
    if (this.taskSearchInput) this.taskSearchInput.value = "";
    this.currentFilter = "all";
    document.querySelectorAll(".filter-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.filter === "all");
    });
    this.renderTaskList();
  }

  async openTaskDetail(taskId) {
  }

  async openTaskDetail(taskId) {
    try {
      const resp = await fetch(`/api/tasks/${taskId}`);
      const res = await resp.json();
      if (res.code !== 0) {
        alert("获取任务详情失败: " + res.message);
        return;
      }

      const task = res.data;
      this.currentTask = task;
      this.renderTaskDetail(task);
      this.showScreen("detail");

      // 若当前激活的是字幕 Tab，自动载入字幕数据
      const activeTabBtn = document.querySelector(".tab-btn.active");
      if (activeTabBtn && activeTabBtn.dataset.tab === "subtitles") {
        this.loadSubtitles(taskId);
      }

      // 若任务处于运行态或排队态，激活 SSE 实时流 (支持 ?no_sse 用于自动化无挂起快照)
      if (task.status === "running" || task.status === "queued" || task.status === "waiting_gpu") {
        if (!window.location.search.includes("no_sse")) {
          this.startSSE(taskId);
        }
      }
    } catch (e) {
      alert("网络请求失败: " + e.message);
    }
  }

  renderTaskDetail(task) {
    this.detailTitle.textContent = task.title;

    // 标签栏
    const formalBadge = task.is_legacy 
      ? `<span class="tag-badge tag-legacy">历史产物 (只读)</span>` 
      : `<span class="tag-badge tag-formal">正式任务 (可续跑/可重渲染)</span>`;
    const debugBadge = task.is_debug ? `<span class="tag-badge tag-debug">调试任务</span>` : "";
    const langBadge = `<span class="tag-badge tag-lang-${task.lang}">${task.lang.toUpperCase()}</span>`;
    const modeBadge = `<span class="tag-badge tag-mode">${task.mode.toUpperCase()}</span>`;
    const idBadge = `<span class="tag-badge tag-mode">ID: ${task.task_id}</span>`;
    const engId = task.engine_id || "sakura-14b";
    const isCloud = engId.includes("chat") || engId.includes("api") || engId.includes("gpt");
    const engBadge = `<span class="tag-badge ${isCloud ? 'tag-formal' : ''}" style="${isCloud ? 'background:rgba(56,189,248,0.18);color:#38bdf8;border:1px solid rgba(56,189,248,0.4);' : ''}">引擎: ${escapeHtml(engId)}</span>`;
    let costBadge = "";
    if (task.cost_estimate && task.cost_estimate.cost !== undefined && task.cost_estimate.cost > 0) {
      costBadge = `<span class="tag-badge" style="background:rgba(16,185,129,0.18);color:#10b981;border:1px solid rgba(16,185,129,0.4);">费用: ￥${task.cost_estimate.cost.toFixed(4)} ${task.cost_estimate.currency || 'CNY'}</span>`;
    }
    let tokenBadge = "";
    if (task.token_usage && task.token_usage.total_tokens) {
      tokenBadge = `<span class="tag-badge" style="background:rgba(168,85,247,0.18);color:#c084fc;border:1px solid rgba(168,85,247,0.4);">Token: ${task.token_usage.total_tokens.toLocaleString()}</span>`;
    }
    this.detailTags.innerHTML = `${formalBadge} ${debugBadge} ${langBadge} ${modeBadge} ${engBadge} ${costBadge} ${tokenBadge} ${idBadge}`;

    // 状态药丸与控制按钮
    this.detailStatusPill.className = `status-pill status-${task.status}`;
    this.detailStatusPill.textContent = task.status;
    this.detailStatusPill.title = task.status_reason || "";
    if (task.status === "interrupted") {
      this.detailStatusPill.className = "status-pill status-interrupted";
      this.detailStatusPill.textContent = "INTERRUPTED (可恢复)";
      this.detailStatusPill.style.background = "rgba(245,158,11,0.18)";
      this.detailStatusPill.style.color = "#f59e0b";
      this.detailStatusPill.style.border = "1px solid rgba(245,158,11,0.35)";
    } else {
      this.detailStatusPill.style.background = "";
      this.detailStatusPill.style.color = "";
      this.detailStatusPill.style.border = "";
    }

    if (task.status === "running" || task.status === "waiting_gpu") {
      this.btnCancelTask.style.display = "inline-flex";
      this.btnResumeTask.style.display = "none";
      this.liveProgressPanel.style.display = "block";
      this.liveTotalPctText.textContent = `${task.total_pct || 0}%`;
      this.liveTotalProgressBar.style.width = `${task.total_pct || 0}%`;
      if (task.current_stage && task.current_stage !== "-") {
        this.liveStageTitle.textContent = `⚡ 正在执行: [${task.current_stage}] (${task.stage_pct || 0}%)`;
      } else {
        this.liveStageTitle.textContent = "⚡ 正在执行阶段...";
      }
    } else if (task.status === "canceled" || task.status === "interrupted" || (task.can_resume && task.status !== "done")) {
      this.btnCancelTask.style.display = "none";
      this.btnResumeTask.style.display = "inline-flex";
      this.liveProgressPanel.style.display = "none";
    } else {
      this.btnCancelTask.style.display = "none";
      this.btnResumeTask.style.display = "none";
      this.liveProgressPanel.style.display = "none";
    }

    // 视频播放器 (HTTP 206 流媒体, R4 规范: poster 真实对白帧 + loadeddata seek 0.1s 根治黑屏)
    if (this.btnDetailDownloadVideo) {
      this.btnDetailDownloadVideo.style.display = task.has_video ? "inline-flex" : "none";
    }
    if (task.has_video) {
      this.detailVideo.style.display = "block";
      this.videoEmptyPlaceholder.style.display = "none";
      this.videoFileName.textContent = task.video_name;

      // R4 规范: 播放器黑屏根治: 注入第一张真实对白帧作为 poster
      this.detailVideo.poster = `/api/tasks/${task.task_id}/frame?time=1.0`;

      const currentSrc = this.detailVideo.getAttribute("src");
      const targetSrc = `/api/tasks/${task.task_id}/video`;
      if (currentSrc !== targetSrc) {
        this.detailVideo.src = targetSrc;
        this.detailVideo.load();
      }

      // loadeddata 触发时前进至 0.1 秒，激活视频第一帧画面绘制
      const seekToDialogue = () => {
        try {
          if (this.detailVideo.currentTime < 0.1) {
            this.detailVideo.currentTime = 0.1;
          }
        } catch (_) {}
      };
      this.detailVideo.addEventListener("loadeddata", seekToDialogue, { once: true });
    } else {
      this.detailVideo.removeAttribute("poster");
      this.detailVideo.style.display = "none";
      this.videoEmptyPlaceholder.style.display = "flex";
      this.videoFileName.textContent = "尚未生成成片";
    }

    // 产物表格 (S2: 包含第4列操作下载)
    this.productsCount.textContent = `${task.products.length} 件产物`;
    this.productsTableBody.innerHTML = task.products.map(p => `
      <tr>
        <td><strong>${escapeHtml(p.name)}</strong></td>
        <td>${p.size_human}</td>
        <td>${p.modified_at.substring(0, 19).replace("T", " ")}</td>
        <td style="text-align: right;">
          <a class="btn btn-outline btn-xs" href="/api/tasks/${task.task_id}/file/${encodeURIComponent(p.name)}" download="${task.task_id}_${p.name}">⬇ 下载</a>
        </td>
      </tr>
    `).join("");

    // 流水线阶段 Tracker
    this.stagesSummary.textContent = `${task.stages.filter(s => s.status === 'completed').length} / ${task.stages.length} 阶段完成`;
    this.pipelineTrack.innerHTML = task.stages.map(st => {
      const isCompleted = st.status === "completed";
      const isSkipped = st.status === "skipped";
      const icon = isCompleted ? "✓" : (isSkipped ? "⏸" : "⏳");
      const statusClass = isCompleted ? "completed" : (isSkipped ? "skipped" : "pending");

      return `
        <div class="stage-row ${statusClass}">
          <div class="stage-info-left">
            <span class="stage-status-icon">${icon}</span>
            <div>
              <div class="stage-name">${escapeHtml(st.display_name)}</div>
              <div class="stage-tool">工具/指纹: ${escapeHtml(st.tool_version)}</div>
            </div>
          </div>
          <span class="status-pill status-${st.status}">${st.status}</span>
        </div>
      `;
    }).join("");

    // 日志 Tab
    if (!this.currentEventSource) {
      this.logContent.textContent = task.recent_log || "暂无日志输出";
    }

    // Manifest Tab
    this.manifestContent.textContent = JSON.stringify(task.manifest, null, 2);
  }

  // ========================================================
  // P3 / R1 / R2: 字幕编辑器核心逻辑 (全屏独立视图、分页、行内改字、同源单帧预览、保存、重渲染)
  // ========================================================
  async loadSubtitles(taskId, isFullscreen = false) {
    try {
      const loadingRow = `<tr><td colspan="4" style="text-align:center; color: var(--text-dim); padding: 20px;">⏳ 正在读取对白数据...</td></tr>`;
      if (this.subtitlesTableBody) this.subtitlesTableBody.innerHTML = loadingRow;
      if (this.fsSubtitlesTableBody) this.fsSubtitlesTableBody.innerHTML = `<tr><td colspan="3" style="text-align:center; color: var(--text-dim); padding: 20px;">⏳ 正在读取对白数据...</td></tr>`;

      const resp = await fetch(`/api/tasks/${taskId}/subtitles`);
      const res = await resp.json();
      if (res.code === 0 && Array.isArray(res.data)) {
        this.subtitlesData = res.data;
        this.originalSubtitlesJson = JSON.stringify(this.subtitlesData);
        this.isSubtitlesDirty = false;
        this.updateDirtyState(false);
        const countStr = `共 ${this.subtitlesData.length} 条对白`;
        if (this.subtitlesTotalCount) this.subtitlesTotalCount.textContent = countStr;
        if (this.fsSubtitlesCount) this.fsSubtitlesCount.textContent = countStr;
        this.currentSubPage = 1;
        this.selectedSubtitleIdx = -1;
        this.renderSubtitlesPage();

        // R2 规范: 进入编辑器默认选中第 1 行并显示其 start + 0.2s 画面，禁止停留在 time=0 的黑屏标题卡
        if (this.subtitlesData.length > 0) {
          this.selectSubtitleRow(0, true);
        }
      } else {
        const errRow = `<tr><td colspan="4" style="text-align:center; color: var(--amber); padding: 20px;">⚠ ${res.message || '暂无字幕数据'}</td></tr>`;
        if (this.subtitlesTableBody) this.subtitlesTableBody.innerHTML = errRow;
        if (this.fsSubtitlesTableBody) this.fsSubtitlesTableBody.innerHTML = `<tr><td colspan="3" style="text-align:center; color: var(--amber); padding: 20px;">⚠ ${res.message || '暂无字幕数据'}</td></tr>`;
        if (this.subtitlesTotalCount) this.subtitlesTotalCount.textContent = "共 0 条对白";
        if (this.fsSubtitlesCount) this.fsSubtitlesCount.textContent = "共 0 条对白";
      }
    } catch (e) {
      const exRow = `<tr><td colspan="4" style="text-align:center; color: var(--text-dim); padding: 20px;">读取字幕异常: ${e.message}</td></tr>`;
      if (this.subtitlesTableBody) this.subtitlesTableBody.innerHTML = exRow;
      if (this.fsSubtitlesTableBody) this.fsSubtitlesTableBody.innerHTML = `<tr><td colspan="3" style="text-align:center; color: var(--text-dim); padding: 20px;">读取字幕异常: ${e.message}</td></tr>`;
    }
  }

  renderSubtitlesPage() {
    if (!this.subtitlesData || this.subtitlesData.length === 0) {
      if (this.subtitlesTableBody) this.subtitlesTableBody.innerHTML = `<tr><td colspan="4" style="text-align:center; color: var(--text-dim); padding: 20px;">暂无字幕数据</td></tr>`;
      if (this.fsSubtitlesTableBody) this.fsSubtitlesTableBody.innerHTML = `<tr><td colspan="3" style="text-align:center; color: var(--text-dim); padding: 20px;">暂无字幕数据</td></tr>`;
      if (this.pageInfo) this.pageInfo.textContent = "第 0 / 0 页";
      if (this.fsPageInfo) this.fsPageInfo.textContent = "第 0 / 0 页 (共 0 条)";
      if (this.btnFirstPage) this.btnFirstPage.disabled = true;
      if (this.btnPrevPage) this.btnPrevPage.disabled = true;
      if (this.btnNextPage) this.btnNextPage.disabled = true;
      if (this.btnLastPage) this.btnLastPage.disabled = true;
      if (this.fsBtnFirstPage) this.fsBtnFirstPage.disabled = true;
      if (this.fsBtnPrevPage) this.fsBtnPrevPage.disabled = true;
      if (this.fsBtnNextPage) this.fsBtnNextPage.disabled = true;
      if (this.fsBtnLastPage) this.fsBtnLastPage.disabled = true;
      return;
    }

    const total = this.subtitlesData.length;
    const maxPage = Math.max(1, Math.ceil(total / this.pageSize));
    if (this.currentSubPage > maxPage) this.currentSubPage = maxPage;
    if (this.currentSubPage < 1) this.currentSubPage = 1;

    const startIdx = (this.currentSubPage - 1) * this.pageSize;
    const endIdx = Math.min(total, startIdx + this.pageSize);
    const pageItems = this.subtitlesData.slice(startIdx, endIdx);

    const pageText = `第 ${this.currentSubPage} / ${maxPage} 页 (共 ${total} 条)`;
    if (this.pageInfo) this.pageInfo.textContent = pageText;
    if (this.fsPageInfo) this.fsPageInfo.textContent = pageText;

    const isFirst = (this.currentSubPage === 1);
    const isLast = (this.currentSubPage === maxPage);

    if (this.btnFirstPage) this.btnFirstPage.disabled = isFirst;
    if (this.btnPrevPage) this.btnPrevPage.disabled = isFirst;
    if (this.btnNextPage) this.btnNextPage.disabled = isLast;
    if (this.btnLastPage) this.btnLastPage.disabled = isLast;

    if (this.fsBtnFirstPage) this.fsBtnFirstPage.disabled = isFirst;
    if (this.fsBtnPrevPage) this.fsBtnPrevPage.disabled = isFirst;
    if (this.fsBtnNextPage) this.fsBtnNextPage.disabled = isLast;
    if (this.fsBtnLastPage) this.fsBtnLastPage.disabled = isLast;

    let originalItems = [];
    try {
      originalItems = JSON.parse(this.originalSubtitlesJson);
    } catch (_) {}

    // 1. 详情页 Tab 内置表格渲染 (若存在)
    if (this.subtitlesTableBody) {
      this.subtitlesTableBody.innerHTML = pageItems.map((item, idx) => {
        const globalIdx = startIdx + idx;
        const isSelected = (this.selectedSubtitleIdx === globalIdx);
        const isDirty = (originalItems[globalIdx] && originalItems[globalIdx].zh !== item.zh);
        const timeRangeStr = `${item.start_str || item.start} - ${item.end_str || item.end}`;
        const srcText = item.src || item.ja || "";
        const dupBadge = item.duplicate_translation 
          ? `<span class="tag-badge tag-warning" style="margin-left: 6px; font-size: 11px; background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4);" title="Z2 标记: 源文本差异明显但输出了重复译文，待人工复核">⚠️ 待复核</span>` 
          : "";

        return `
          <tr class="sub-row ${isSelected ? 'selected-row' : ''}" data-global-idx="${globalIdx}">
            <td class="sub-idx">${item.index || (globalIdx + 1)}</td>
            <td>
              <span class="sub-time" data-time="${item.start}" title="点击精确预览画面 (start + 0.2s)">${timeRangeStr}</span>
            </td>
            <td class="sub-src">${escapeHtml(srcText)}</td>
            <td>
              <div style="display: flex; align-items: center; gap: 6px;">
                <input type="text" class="zh-edit-input ${isDirty ? 'is-dirty' : ''}" data-global-idx="${globalIdx}" value="${escapeHtml(item.zh || '')}" placeholder="输入中文译文...">
                ${dupBadge}
              </div>
            </td>
          </tr>
        `;
      }).join("");
    }

    // 2. R1 规范: 全屏独立字幕编辑器表格渲染 (时间 110px / 原文 45% / 译文 45%)
    if (this.fsSubtitlesTableBody) {
      this.fsSubtitlesTableBody.innerHTML = pageItems.map((item, idx) => {
        const globalIdx = startIdx + idx;
        const isSelected = (this.selectedSubtitleIdx === globalIdx);
        const isDirty = (originalItems[globalIdx] && originalItems[globalIdx].zh !== item.zh);
        const timeRangeStr = `${formatTimeShort(item.start)} - ${formatTimeShort(item.end)}`;
        const srcText = item.src || item.ja || "";
        const dupBadge = item.duplicate_translation 
          ? `<span class="tag-badge tag-warning" style="margin-left: 6px; font-size: 11px; background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4);" title="Z2 标记: 源文本差异明显但输出了重复译文，待人工复核">⚠️ 待复核</span>` 
          : "";

        return `
          <tr class="editor-sub-row ${isSelected ? 'selected-row' : ''}" data-global-idx="${globalIdx}">
            <td class="editor-sub-time">
              <span class="sub-time" data-time="${item.start}" title="点击在左侧精确预览画面 (start + 0.2s)">${timeRangeStr}</span>
            </td>
            <td class="editor-sub-src">${escapeHtml(srcText)}</td>
            <td class="editor-sub-zh">
              <div style="display: flex; align-items: center; gap: 6px;">
                <input type="text" class="zh-edit-input ${isDirty ? 'is-dirty' : ''}" data-global-idx="${globalIdx}" value="${escapeHtml(item.zh || '')}" placeholder="输入中文译文...">
                ${dupBadge}
              </div>
            </td>
          </tr>
        `;
      }).join("");
    }

    // 通用行点击事件绑定 (支持详情 Tab 与全屏独立视图)
    document.querySelectorAll(".sub-row, .editor-sub-row").forEach(row => {
      const globalIdx = parseInt(row.dataset.globalIdx, 10);
      row.addEventListener("click", (e) => {
        if (e.target.tagName.toLowerCase() !== "input") {
          this.selectSubtitleRow(globalIdx);
        }
      });
    });

    // 时间戳点击快速预览
    document.querySelectorAll(".sub-time").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const row = btn.closest(".sub-row, .editor-sub-row");
        if (row) {
          const gIdx = parseInt(row.dataset.globalIdx, 10);
          this.selectSubtitleRow(gIdx);
        }
      });
    });

    // 行内改字事件监听与脏标记响应
    document.querySelectorAll(".zh-edit-input").forEach(input => {
      input.addEventListener("focus", () => {
        const gIdx = parseInt(input.dataset.globalIdx, 10);
        this.selectSubtitleRow(gIdx, false);
      });

      input.addEventListener("input", (e) => {
        const gIdx = parseInt(e.target.dataset.globalIdx, 10);
        const val = e.target.value;
        this.subtitlesData[gIdx].zh = val;

        let origZh = "";
        try {
          origZh = JSON.parse(this.originalSubtitlesJson)[gIdx]?.zh || "";
        } catch (_) {}

        const isRowDirty = (val !== origZh);
        // 双向同步所有对应 input 的脏状态与内容
        document.querySelectorAll(`.zh-edit-input[data-global-idx="${gIdx}"]`).forEach(inp => {
          if (inp !== e.target) inp.value = val;
          if (isRowDirty) {
            inp.classList.add("is-dirty");
          } else {
            inp.classList.remove("is-dirty");
          }
        });

        this.checkDirtyState();
      });
    });
  }

  selectSubtitleRow(globalIdx, triggerPreview = true) {
    this.selectedSubtitleIdx = globalIdx;
    document.querySelectorAll(".sub-row, .editor-sub-row").forEach(r => {
      if (parseInt(r.dataset.globalIdx, 10) === globalIdx) {
        r.classList.add("selected-row");
      } else {
        r.classList.remove("selected-row");
      }
    });

    if (triggerPreview && this.subtitlesData[globalIdx]) {
      const item = this.subtitlesData[globalIdx];
      // R2 规范: 自动跳到该行 start + 0.2s，避开切镜黑场，展现完整浮现后的 libass 同源渲染
      const rawStart = parseFloat(item.start) || 0;
      const targetTime = Math.max(0, +(rawStart + 0.2).toFixed(2));
      const timeLabel = `${formatSeconds(targetTime)} (start + 0.2s)`;
      this.requestFramePreview(targetTime, timeLabel);
    }
  }

  requestFramePreview(timeSeconds, timeLabel, immediate = false) {
    if (!this.currentTask) return;
    if (this.previewTimeTag) this.previewTimeTag.textContent = timeLabel;
    if (this.fsPreviewTimeTag) this.fsPreviewTimeTag.textContent = timeLabel;

    if (this.previewThrottleTimer) {
      clearTimeout(this.previewThrottleTimer);
    }

    const doFetch = async () => {
      if (this.previewAbortController) {
        this.previewAbortController.abort();
      }
      this.previewAbortController = new AbortController();

      if (this.previewLoading) this.previewLoading.style.display = "block";
      if (this.previewPlaceholder) this.previewPlaceholder.style.display = "none";
      if (this.fsPreviewLoading) this.fsPreviewLoading.style.display = "block";
      if (this.fsPreviewPlaceholder) this.fsPreviewPlaceholder.style.display = "none";

      const tStart = performance.now();
      try {
        const url = `/api/tasks/${this.currentTask.task_id}/frame?time=${encodeURIComponent(timeSeconds)}&_t=${Date.now()}`;
        const resp = await fetch(url, { signal: this.previewAbortController.signal });
        const elapsedMs = Math.round(performance.now() - tStart);

        if (resp.ok) {
          const blob = await resp.blob();
          const imgUrl = URL.createObjectURL(blob);
          if (this.previewImg) {
            this.previewImg.src = imgUrl;
            this.previewImg.style.display = "block";
          }
          if (this.fsPreviewImg) {
            this.fsPreviewImg.src = imgUrl;
            this.fsPreviewImg.style.display = "block";
          }
          // R3 单帧耗时展示 (冷/热明确分开)
          const isHot = elapsedMs < 90;
          const costStr = `渲染耗时: ${elapsedMs}ms (${isHot ? '热缓存命中' : '冷启动渲染'})`;
          if (this.fsFrameRenderCost) this.fsFrameRenderCost.textContent = costStr;
        } else {
          const errNotice = `<span style="color:var(--amber);">⚠ 提取此帧失败 (${resp.status})</span>`;
          if (this.previewPlaceholder) {
            this.previewPlaceholder.innerHTML = errNotice;
            this.previewPlaceholder.style.display = "flex";
          }
          if (this.fsPreviewPlaceholder) {
            this.fsPreviewPlaceholder.innerHTML = errNotice;
            this.fsPreviewPlaceholder.style.display = "flex";
          }
          if (this.previewImg) this.previewImg.style.display = "none";
          if (this.fsPreviewImg) this.fsPreviewImg.style.display = "none";
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          const errNotice = `<span style="color:var(--text-dim);">提取中断: ${err.message}</span>`;
          if (this.previewPlaceholder) {
            this.previewPlaceholder.innerHTML = errNotice;
            this.previewPlaceholder.style.display = "flex";
          }
          if (this.fsPreviewPlaceholder) {
            this.fsPreviewPlaceholder.innerHTML = errNotice;
            this.fsPreviewPlaceholder.style.display = "flex";
          }
          if (this.previewImg) this.previewImg.style.display = "none";
          if (this.fsPreviewImg) this.fsPreviewImg.style.display = "none";
        }
      } finally {
        if (this.previewLoading) this.previewLoading.style.display = "none";
        if (this.fsPreviewLoading) this.fsPreviewLoading.style.display = "none";
      }
    };

    if (immediate) {
      doFetch();
    } else {
      // M1 规范: ≥ 150ms 节流 + AbortController 取消前序未完成请求
      this.previewThrottleTimer = setTimeout(doFetch, 150);
    }
  }

  checkDirtyState() {
    let dirty = false;
    try {
      const orig = JSON.parse(this.originalSubtitlesJson);
      for (let i = 0; i < this.subtitlesData.length; i++) {
        if (this.subtitlesData[i].zh !== orig[i]?.zh) {
          dirty = true;
          break;
        }
      }
    } catch (_) {
      dirty = true;
    }
    this.updateDirtyState(dirty);
  }

  updateDirtyState(dirty) {
    this.isSubtitlesDirty = dirty;
    if (this.subtitlesDirtyBadge) {
      this.subtitlesDirtyBadge.style.display = dirty ? "inline-block" : "none";
    }
    if (this.fsSubtitlesDirtyBadge) {
      this.fsSubtitlesDirtyBadge.style.display = dirty ? "inline-block" : "none";
    }
    if (this.btnSaveSubtitles) {
      this.btnSaveSubtitles.disabled = !dirty;
    }
    if (this.fsBtnSaveSubtitles) {
      this.fsBtnSaveSubtitles.disabled = !dirty;
    }
  }

  async saveSubtitles() {
    if (!this.currentTask) return;
    try {
      if (this.btnSaveSubtitles) {
        this.btnSaveSubtitles.disabled = true;
        this.btnSaveSubtitles.textContent = "⏳ 正在保存...";
      }
      if (this.fsBtnSaveSubtitles) {
        this.fsBtnSaveSubtitles.disabled = true;
        this.fsBtnSaveSubtitles.textContent = "⏳ 正在保存...";
      }
      const resp = await fetch(`/api/tasks/${this.currentTask.task_id}/subtitles`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subtitles: this.subtitlesData })
      });
      const res = await resp.json();
      if (res.code === 0) {
        this.originalSubtitlesJson = JSON.stringify(this.subtitlesData);
        this.updateDirtyState(false);
        this.renderSubtitlesPage();
        this.appendLogLine(`[系统] 字幕修改已保存回 chinese.json (已即时更新 ASS 排版)`);
        // 关键: 保存后若当前有选中的行，立刻强制刷新该行对应的单帧画面 (≤1.5s 快速响应)
        if (this.selectedSubtitleIdx >= 0 && this.subtitlesData[this.selectedSubtitleIdx]) {
          const item = this.subtitlesData[this.selectedSubtitleIdx];
          const rawStart = parseFloat(item.start) || 0;
          const targetTime = Math.max(0, +(rawStart + 0.2).toFixed(2));
          const timeLabel = `${formatSeconds(targetTime)} (start + 0.2s)`;
          this.requestFramePreview(targetTime, timeLabel, true);
        }
      } else {
        alert("保存失败: " + res.message);
      }
    } catch (e) {
      alert("保存请求异常: " + e.message);
    } finally {
      if (this.btnSaveSubtitles) {
        this.btnSaveSubtitles.textContent = "💾 保存修改";
        this.btnSaveSubtitles.disabled = !this.isSubtitlesDirty;
      }
      if (this.fsBtnSaveSubtitles) {
        this.fsBtnSaveSubtitles.textContent = "💾 保存修改";
        this.fsBtnSaveSubtitles.disabled = !this.isSubtitlesDirty;
      }
    }
  }

  async rerenderCurrentTask() {
    if (!this.currentTask) return;
    if (this.isSubtitlesDirty) {
      if (confirm("检测到有尚未保存的字幕修改，是否先自动保存再开始增量重渲染？")) {
        await this.saveSubtitles();
      } else {
        return;
      }
    }

    try {
      this.btnRerender.disabled = true;
      const resp = await fetch(`/api/tasks/${this.currentTask.task_id}/rerender`, {
        method: "POST"
      });
      const res = await resp.json();
      if (res.code === 0) {
        this.appendLogLine(`[系统] 增量重渲染已触发: 跳过 OCR 与翻译，重新执行排版与压制`);
        this.detailStatusPill.className = "status-pill status-running";
        this.detailStatusPill.textContent = "RUNNING";
        this.liveProgressPanel.style.display = "block";
        this.startSSE(this.currentTask.task_id);
      } else {
        alert("重渲染提交失败: " + res.message);
      }
    } catch (e) {
      alert("请求异常: " + e.message);
    } finally {
      this.btnRerender.disabled = false;
    }
  }

  startSSE(taskId) {
    this.stopSSE();

    const es = new EventSource(`/api/tasks/${taskId}/events`);
    this.currentEventSource = es;

    this.liveProgressPanel.style.display = "block";
    this.btnCancelTask.style.display = "inline-flex";
    this.btnResumeTask.style.display = "none";

    es.addEventListener("stage_change", (e) => {
      try {
        const d = JSON.parse(e.data);
        this.liveStageTitle.textContent = `⚡ ${d.message || d.stage}`;
        if (d.stage === "resume") {
          this.appendLogLine(`[断点恢复] ${d.message}`);
        }
      } catch (err) {}
    });

    es.addEventListener("stage_log", (e) => {
      try {
        const d = JSON.parse(e.data);
        this.appendLogLine(`[${d.timestamp || ''}] ${d.text}`);

        if (d.total_pct !== undefined) {
          this.liveTotalPctText.textContent = `${d.total_pct}%`;
          this.liveTotalProgressBar.style.width = `${d.total_pct}%`;
        }
        if (d.current_stage) {
          this.liveStageTitle.textContent = `⚡ 正在执行: [${d.current_stage}] (${d.stage_pct || 0}%)`;
        }
      } catch (err) {}
    });

    es.addEventListener("task_complete", (e) => {
      try {
        const d = JSON.parse(e.data);
        this.appendLogLine(`[系统] ${d.message}`);
        this.liveTotalProgressBar.style.width = "100%";
        this.liveTotalPctText.textContent = "100.0%";
        this.stopSSE();
        // 自动重新拉取任务详情并自动播放成片
        setTimeout(() => {
          this.openTaskDetail(taskId);
        }, 1000);
      } catch (err) {}
    });

    es.addEventListener("task_canceled", (e) => {
      try {
        const d = JSON.parse(e.data);
        this.appendLogLine(`[取消成功] ${d.message}`);
        this.detailStatusPill.className = "status-pill status-canceled";
        this.detailStatusPill.textContent = "CANCELED";
        this.btnCancelTask.style.display = "none";
        this.btnResumeTask.style.display = "inline-flex";
        this.liveStageTitle.textContent = "⚠ 任务已取消 (GPU 租约已安全释放)";
        this.stopSSE();
      } catch (err) {}
    });

    es.addEventListener("task_interrupted", (e) => {
      try {
        const d = JSON.parse(e.data);
        this.appendLogLine(`[中断提示] ${d.message}`);
        this.detailStatusPill.className = "status-pill status-interrupted";
        this.detailStatusPill.textContent = "INTERRUPTED (可恢复)";
        this.detailStatusPill.style.background = "rgba(245,158,11,0.18)";
        this.detailStatusPill.style.color = "#f59e0b";
        this.detailStatusPill.style.border = "1px solid rgba(245,158,11,0.35)";
        this.btnCancelTask.style.display = "none";
        this.btnResumeTask.style.display = "inline-flex";
        this.liveStageTitle.textContent = "⏸ 任务已安全中断 (已保留阶段产物，支持一键断点续跑)";
        this.stopSSE();
        this.loadTasks();
      } catch (err) {}
    });

    es.addEventListener("task_error", (e) => {
      try {
        const d = JSON.parse(e.data);
        this.appendLogLine(`[错误] ${d.message || d.error}`);
        this.detailStatusPill.className = "status-pill status-failed";
        this.detailStatusPill.textContent = "FAILED";
        this.btnCancelTask.style.display = "none";
        this.btnResumeTask.style.display = "inline-flex";
        this.stopSSE();
      } catch (err) {}
    });

    es.onerror = () => {
      // 浏览器 EventSource 会自动根据 Last-Event-ID 重试回放
    };
  }

  stopSSE() {
    if (this.currentEventSource) {
      this.currentEventSource.close();
      this.currentEventSource = null;
    }
  }

  appendLogLine(text) {
    this.logContent.textContent += (this.logContent.textContent ? "\n" : "") + text;
    if (this.chkAutoScroll.checked) {
      this.logContent.scrollTop = this.logContent.scrollHeight;
    }
  }

  async resumeCurrentTask() {
    if (!this.currentTask) return;
    try {
      this.btnResumeTask.disabled = true;
      const resp = await fetch(`/api/tasks/${this.currentTask.task_id}/start`, { method: "POST" });
      const res = await resp.json();
      if (res.code === 0) {
        this.startSSE(this.currentTask.task_id);
      } else {
        alert("启动失败: " + res.message);
      }
    } catch (e) {
      alert("请求异常: " + e.message);
    } finally {
      this.btnResumeTask.disabled = false;
    }
  }

  async cancelCurrentTask() {
    if (!this.currentTask) return;
    try {
      this.btnCancelTask.disabled = true;
      const resp = await fetch(`/api/tasks/${this.currentTask.task_id}/cancel`, { method: "POST" });
      const res = await resp.json();
      if (res.code === 0) {
        this.appendLogLine("[系统] 取消指令已发出，正在强制回收 GPU 租约并在 3 秒内安全退出...");
      }
    } catch (e) {
      alert("取消请求失败: " + e.message);
    } finally {
      this.btnCancelTask.disabled = false;
    }
  }

  onEngineChange() {
    if (!this.selectEngine || !this.engineCostEstimateRow) return;
    const selectedId = this.selectEngine.value;
    const eng = this.availableEngines.find(e => e.id === selectedId);
    if (eng && eng.type === "api") {
      this.engineCostEstimateRow.style.display = "block";
      const inRate = eng.pricing.input_per_m || 0;
      const outRate = eng.pricing.output_per_m || 0;
      const curr = eng.pricing.currency || "CNY";
      if (this.engineCostEstimateText) {
        this.engineCostEstimateText.textContent = `约 ￥${(inRate * 0.02 + outRate * 0.01).toFixed(3)} ~ ￥${(inRate * 0.08 + outRate * 0.04).toFixed(3)} ${curr} (费率: 入 ￥${inRate}/M, 出 ￥${outRate}/M)`;
      }
    } else {
      this.engineCostEstimateRow.style.display = "none";
    }
  }

  async loadAvailableEngines() {
    try {
      const resp = await fetch("/api/system/engines");
      const res = await resp.json();
      if (res.code === 0 && Array.isArray(res.data)) {
        this.availableEngines = res.data;
        if (this.selectEngine) {
          this.selectEngine.innerHTML = res.data.map(e => {
            const keyHint = e.type === "api"
              ? (e.configured ? ` [已配密钥: ${e.masked_key}]` : " [未配置密钥]")
              : " [本地免密]";
            return `<option value="${e.id}">${escapeHtml(e.name)}${keyHint}</option>`;
          }).join("");
          this.onEngineChange();
        }
      }
    } catch (e) {
      console.warn("加载翻译引擎列表失败:", e);
    }
  }

  async loadServerInputFiles() {
    try {
      const resp = await fetch("/api/server/input_files");
      const res = await resp.json();
      if (res.code === 0 && res.data) {
        this.serverInputFiles = res.data;
        this.selectQuickFile.innerHTML = `<option value="">-- 点击选择 input / ocr_input 目录中的片源 --</option>` +
          res.data.map(f => `<option value="${f.rel_path}">[${f.folder}] ${f.name} (${f.size_human})</option>`).join("");
      }
    } catch (e) {
      console.warn("加载服务器输入文件失败:", e);
    }
  }

  async openNewTaskModal(defaultFilename = "") {
    this.modalNewTask.style.display = "flex";
    if (this.uploadProgressContainer) {
      this.uploadProgressContainer.style.display = "none";
    }
    if (defaultFilename) {
      this.inputVideoPath.value = defaultFilename;
      this.inputTaskTitle.value = defaultFilename.substring(0, defaultFilename.lastIndexOf('.')) || defaultFilename;
    }

    await Promise.all([
      this.loadServerInputFiles(),
      this.loadAvailableEngines()
    ]);
  }

  closeNewTaskModal() {
    this.modalNewTask.style.display = "none";
    if (this.uploadProgressContainer) {
      this.uploadProgressContainer.style.display = "none";
    }
    this.formNewTask.reset();
  }

  async handleFileDrop(file) {
    if (!file) return;
    this.openNewTaskModal(file.name);

    const MAX_4GB = 4 * 1024 * 1024 * 1024;
    if (file.size > MAX_4GB) {
      alert(`单文件不能超过 4 GB 限制（当前文件大小: ${formatBytes(file.size)}）`);
      return;
    }

    // Z7 客户端毫秒级预检: 若服务器已有同名且大小完全一致的片源，直接选中免传
    if (this.serverInputFiles && Array.isArray(this.serverInputFiles)) {
      const matched = this.serverInputFiles.find(
        f => f.name === file.name && f.size_bytes === file.size && f.folder === "ocr_input"
      );
      if (matched) {
        if (this.uploadProgressContainer) {
          this.uploadProgressContainer.style.display = "block";
          this.uploadProgressBar.style.width = "100%";
          this.uploadPercentText.textContent = "100%";
          this.uploadStatusText.textContent = `✓ 该片源已存在，已为你选中: ${matched.rel_path}`;
          this.uploadStatusText.style.color = "#10b981";
        }
        this.inputVideoPath.value = matched.rel_path;
        this.selectQuickFile.value = matched.rel_path;
        return;
      }
    }

    try {
      await this.uploadFile(file);
    } catch (e) {
      console.error("上传片源失败:", e);
    }
  }

  uploadFile(file) {
    return new Promise((resolve, reject) => {
      const submitBtn = document.getElementById("btnSubmitTask");
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = "⏳ 文件正在导入中...";
      }

      const sizeStr = formatBytes(file.size);
      if (this.uploadProgressContainer) {
        this.uploadProgressContainer.style.display = "block";
        this.uploadProgressBar.style.width = "0%";
        this.uploadPercentText.textContent = "0%";
        this.uploadStatusText.textContent = `正在导入 ${file.name} (${sizeStr})…`;
        this.uploadStatusText.style.color = "#94a3b8";
      }

      const formData = new FormData();
      formData.append("file", file);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload", true);

      xhr.upload.onprogress = (evt) => {
        if (evt.lengthComputable && this.uploadProgressBar) {
          const percent = Math.min(99, Math.round((evt.loaded / evt.total) * 100));
          this.uploadProgressBar.style.width = `${percent}%`;
          this.uploadPercentText.textContent = `${percent}%`;
          this.uploadStatusText.textContent = `正在导入 ${file.name} (${sizeStr})… ${percent}%`;
        }
      };

      xhr.onload = async () => {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "🚀 开始运行流水线";
        }

        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const res = JSON.parse(xhr.responseText);
            if (res.code === 0 && res.data) {
              const msg = (res.existed || (res.message && res.message.includes("已存在")))
                ? `✓ 该片源已存在，已为你选中: ${res.data.rel_path}`
                : `✓ 已成功导入至 ${res.data.rel_path}`;

              if (this.uploadProgressBar) {
                this.uploadProgressBar.style.width = "100%";
                this.uploadPercentText.textContent = "100%";
                this.uploadStatusText.textContent = msg;
                this.uploadStatusText.style.color = "#10b981";
              }
              // 把返回的 rel_path 填进输入框
              this.inputVideoPath.value = res.data.rel_path;
              // 自动刷新下拉框列表
              await this.loadServerInputFiles();
              this.selectQuickFile.value = res.data.rel_path;
              resolve(res.data);
            } else {
              throw new Error(res.message || "上传失败");
            }
          } catch (err) {
            this.onUploadError(err.message);
            reject(err);
          }
        } else {
          let errMsg = `上传失败 (${xhr.status})`;
          try {
            const errJson = JSON.parse(xhr.responseText);
            errMsg = errJson.detail || errJson.message || errMsg;
          } catch (_) {}
          this.onUploadError(errMsg);
          reject(new Error(errMsg));
        }
      };

      xhr.onerror = () => {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "🚀 开始运行流水线";
        }
        const errMsg = "网络异常，文件上传失败";
        this.onUploadError(errMsg);
        reject(new Error(errMsg));
      };

      xhr.send(formData);
    });
  }

  onUploadError(msg) {
    if (this.uploadStatusText) {
      this.uploadStatusText.textContent = `✗ 导入失败: ${msg}`;
      this.uploadStatusText.style.color = "#ef4444";
    }
    if (this.uploadProgressBar) {
      this.uploadProgressBar.style.width = "0%";
    }
    alert("导入片源失败: " + msg);
  }

  async submitNewTask() {
    let videoPath = this.inputVideoPath.value.trim().replace(/^["']|["']$/g, '');
    if (!videoPath) {
      alert("请填写视频片源路径！");
      return;
    }

    const payload = {
      video_path: videoPath,
      lang: this.selectLang.value,
      mode: this.selectMode.value,
      engine_id: this.selectEngine ? this.selectEngine.value : "sakura-14b",
      title: this.inputTaskTitle.value.trim(),
      auto_start: true
    };

    const submitBtn = document.getElementById("btnSubmitTask");
    const origBtnText = submitBtn ? submitBtn.textContent : "";
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "⏳ 正在创建并加入队列...";
    }

    try {
      const resp = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const res = await resp.json().catch(() => ({}));
      if (!resp.ok || res.code !== 0) {
        const errDetail = res.detail || res.message || `HTTP ${resp.status}`;
        alert("创建任务失败: " + errDetail);
        return;
      }

      this.closeNewTaskModal();
      const newTask = res.data;
      
      // 刷新列表并自动切换到新任务详情
      await this.loadTasks();
      window.location.hash = `#task=${newTask.task_id}`;
    } catch (e) {
      alert("创建任务异常: " + e.message);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = origBtnText;
      }
    }
  }
}

function formatTimeShort(secs) {
  const s = Math.max(0, parseFloat(secs) || 0);
  const mins = Math.floor(s / 60);
  const remSecs = (s % 60).toFixed(1);
  const mStr = String(mins).padStart(2, "0");
  const sStr = String(remSecs).padStart(4, "0");
  return `${mStr}:${sStr}`;
}

function formatSeconds(secs) {
  const s = Math.max(0, parseFloat(secs) || 0);
  const mins = Math.floor(s / 60);
  const remSecs = (s % 60).toFixed(2);
  const mStr = String(mins).padStart(2, "0");
  const sStr = String(remSecs).padStart(5, "0");
  return `${mStr}:${sStr}`;
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

window.addEventListener("DOMContentLoaded", () => {
  window.app = new WebUIApp();
});
