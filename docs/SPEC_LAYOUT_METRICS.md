# AnimeAutoSub · 字幕布局与画面遮盖客观度量规范 (SPEC_LAYOUT_METRICS.md)

> **文档状态**: 冻结生效 (E4 门禁规范)  
> **制定版本**: v1.0  
> **制定背景**: 废除传统目标检测的 IoU（交并比）指标。IoU 无法区分"字幕文字透出重叠"与"遮罩多余遮盖原画"的物理差异。改为两项正交的像素级硬性指标。

---

## 1. 废除 IoU 的物理根因

- **传统 IoU 缺陷**: 当遮罩框与原字幕框相交时，IoU 达到 0.7 往往看似良好，但若有 10% 的原字幕边缘文字露在遮罩外，人眼观感为**严重的双语文字粘连刺眼（重影灾难）**；反之，若遮罩做成全宽粗黑条，虽然 100% 盖住原字幕，但遮盖了大量原本精美的动漫背景原画。
- **正交双指标体系**: 将评估解耦为**文字阻断性（防止透出）**与**原画通透性（减少遮挡）**两项独立度量。

---

## 2. 核心数学度量定义

设视频分辨率为 $W \times H$，时间 $t$ 处的原始画面帧为 $F_t$。

### 2.1 指标一：原文字幕残留透出率 (Residual Bleed-through Rate, $R_{\text{bleed}}$)
衡量原硬字幕文字笔画被遮罩或新字幕完整覆盖的彻底程度。

- **原始文字二值掩码 $M_{\text{text}}$**: 由 RapidOCR 检测框联合局部 Otsu/自适应二值化提取的原文字符笔画像素集。
- **新覆盖几何掩码 $M_{\text{cover}}$**: 包括 ASS 遮罩多边形区域 $M_{\text{mask}}$ 与新嵌入中文字幕文字包围区 $M_{\text{zh}}$。
- **残留穿透像素集**:
  $$\text{Bleed} = M_{\text{text}} \setminus M_{\text{cover}}$$
- **透出率计算公式**:
  $$R_{\text{bleed}} = \frac{|\text{Bleed}|}{|M_{\text{text}}|}$$

> **硬门禁要求**:
> - 在遮罩模式（`replace_mask`）下：**$R_{\text{bleed}} \le 0.005$ (0.5%)**，即不允许出现原日文文字边缘外露。
> - 在双语并列模式（`stack_below`）下：$R_{\text{bleed}}$ 不适用，转为断言**两组文字包围盒的纵向交叠度为 0**（$\Delta y_{\text{gap}} \ge 8\text{px}$）。

---

### 2.2 指标二：原画额外遮蔽损失率 (Extra Occlusion Rate, $O_{\text{extra}}$) 与 原画露出比
衡量遮罩是否过大、是否遮挡了不必要的动漫背景画面。

- **有效遮盖区**: 覆盖原日文外接矩形（带安全 padding 4px）所需的最小面积 $A_{\text{min\_required}}$。
- **实际遮蔽区 $A_{\text{actual}}$**: ASS 遮罩绘制的多边形面积。
- **多余遮盖面积**:
  $$A_{\text{wasted}} = \max(0, A_{\text{actual}} - A_{\text{min\_required}})$$
- **原画多余遮蔽率**:
  $$O_{\text{extra}} = \frac{A_{\text{wasted}}}{W \times H}$$
- **画面有效露出比例 (Background Reveal Ratio, $P_{\text{reveal}}$)**:
  $$P_{\text{reveal}} = 1.0 - \frac{A_{\text{actual}}}{W \times H}$$

> **硬门禁要求 (不得低于 Legacy 基线)**:
> - **Legacy 基线档位**:
>   - 720p: 遮罩为底部满宽矩形，高度 180px，遮蔽面积 $1280 \times 180 = 230,400\text{ px}$，露出比 $P_{\text{reveal}} = 75.0\%$。
>   - 1080p: 满宽高度 180px，面积 $1920 \times 180 = 345,600\text{ px}$，露出比 $P_{\text{reveal}} = 83.33\%$。
> - **门禁红线**: **任何优化算法下的原画露出比例 $P_{\text{reveal}}$ 严禁低于上述 Legacy 基线**（即 1080p 遮蔽面积不得超过 $345,600\text{ px}$；自适应紧凑遮罩更要求 $P_{\text{reveal}} \ge 90.0\%$）。

---

## 3. 自动化比对与测试算法实现

在 Parity 测试与 Regression 测试中，通过以下无头算法直接对合成帧进行计算：
1. 提取抽检帧的原始帧与压制成片帧。
2. 计算原文字幕 ROI 区域内的差异二值化图：
   - 提取原图文字笔画特征点。
   - 检查成片中对应坐标是否已被遮罩纯色或中文描边完全覆盖。
3. 统计全片黑底遮罩多边形的实际像素总数，断言 $\sum A_{\text{actual}} \le A_{\text{legacy}}$。
