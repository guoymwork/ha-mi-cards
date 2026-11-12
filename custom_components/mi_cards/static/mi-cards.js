/**
 * 米家风格设备卡片 —— Home Assistant Lovelace 自定义卡片
 * ---------------------------------------------------------------------------
 *  custom:mi-device-card    设备小卡片：实物图 + 右上角开关（随状态点亮）+ 点击进入详情
 *  custom:mi-device-detail  设备详情页：大温度圈 / 开关 / 档位选择 / 常用功能列表
 *
 * 纯原生 JS（无 lit、无构建），单文件，可直接放到 HA 的 www 目录后注册为 Lovelace 资源。
 * 用法：把本文件放到 <config>/www/mi-cards.js，并在 Lovelace 资源中新增
 *       /local/mi-cards.js （模块类型 module）。
 */

(() => {
  "use strict";

  const DEFAULT_ACCENT = "#ff6a00";

  /* ------------------------------------------------------------------ 工具 */

  const fireEvent = (node, type, detail, options) => {
    options = options || {};
    detail = detail === null || detail === undefined ? {} : detail;
    const event = new Event(type, {
      bubbles: options.bubbles === undefined ? true : options.bubbles,
      cancelable: Boolean(options.cancelable),
      composed: true,
    });
    event.detail = detail;
    node.dispatchEvent(event);
    return event;
  };

  /** 前端路由跳转（等价于原生 tap_action: navigate） */
  const navigate = (path) => {
    if (!path) return;
    window.history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
    window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
  };

  const esc = (s) =>
    String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);

  const obj = (hass, id) => (hass && id && hass.states ? hass.states[id] : undefined);

  /** 扫地机「正在干活」的状态集合（用于点亮右上角按钮） */
  const VAC_ACTIVE = new Set([
    "cleaning", "returning", "going_to_target", "spot_cleaning",
    "zoned_cleaning", "segment_cleaning", "docked_while_cleaning",
  ]);

  const isOn = (hass, id) => {
    const o = obj(hass, id);
    if (!o) return false;
    if (String(id).indexOf("vacuum.") === 0) return VAC_ACTIVE.has(o.state);
    return ["on", "home", "true", "open", "playing", "heat", "open"].includes(o.state);
  };

  /** select/number 枚举值 -> 友好文案（石头等集成常用英文枚举） */
  const ENUM_LABELS = {
    // 通用档位
    medium: "中等", standard: "标准", high: "高", low: "低",
    vac_and_mop: "清扫+拖地", vacuum: "清扫", mop: "拖地",
    smart: "智能", custom: "自定义", auto: "自动",
    // 电量枚举
    Fully: "电量充足", High: "电量较高", Medium: "电量中等",
    Low: "电量偏低", Empty: "电量耗尽", full: "电量充足",
    // 石头扫地机状态
    unknown: "未知", starting: "启动中", charger_disconnected: "充电器未连接",
    idle: "待机", remote_control_active: "遥控中", cleaning: "清扫中",
    returning_home: "返回基站", manual_mode: "手动模式", charging: "充电中",
    charging_problem: "充电异常", paused: "已暂停", spot_cleaning: "区域清扫",
    error: "故障", shutting_down: "关机中", updating: "固件升级中",
    docking: "对接基站", going_to_target: "前往目标", zoned_cleaning: "区域清扫",
    segment_cleaning: "分区清扫", emptying_the_bin: "集尘中",
    washing_the_mop: "清洗拖布", going_to_wash_the_mop: "前往清洗拖布",
    in_call: "通话中", mapping: "建图中", patrol: "巡逻中",
    attaching_the_mop: "安装拖布", detaching_the_mop: "拆卸拖布",
    charging_complete: "充电完成", device_offline: "设备离线", locked: "已锁定",
    air_drying_stopping: "烘干停止", robot_status_mopping: "拖地中",
    clean_mop_cleaning: "清洗拖布中", clean_mop_mopping: "拖地中",
    segment_mopping: "分区拖地", zoned_mopping: "区域拖地",
    back_to_dock_washing_duster: "返回基站清洗",
    none: "无",
    // 石头 select 枚举
    off: "关闭", deep: "深度", deep_plus: "深度+", fast: "快速",
    custom_water_flow: "自定义水量", smart_mode: "智能模式", custom: "自定义",
    ok: "正常", no_dustbin_or_filter: "无集尘袋或滤网",
    auto_empty_dock_fan_error: "基站集尘风机异常", duct_blockage: "风道堵塞",
    auto_empty_dock_voltage_error: "基站电压异常", water_empty: "缺水",
    waste_water_tank_full: "污水箱已满", maintenance_brush_jammed: "维护刷卡住",
    dirty_tank_latch_open: "污水箱盖未关", no_dustbin: "无集尘袋",
    cleaning_tank_full_or_blocked: "清水箱满或堵塞",
  };

  /** 时间戳（ISO 或 epoch 秒）-> 本地时间 */
  const fmtTime = (raw) => {
    if (raw === null || raw === undefined || raw === "") return "";
    let d = null;
    if (typeof raw === "number") {
      d = new Date(raw > 1e12 ? raw : raw * 1000);
    } else {
      const s = String(raw);
      if (/^\d{4}-\d{2}-\d{2}[T ]/.test(s)) {
        d = new Date(s);
      } else if (/^\d+(\.\d+)?$/.test(s)) {
        const n = parseFloat(s);
        d = new Date(n > 1e12 ? n : n * 1000);
      }
    }
    if (!d || isNaN(d.getTime())) return "";
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };

  /** 时长（小时/分钟单位）-> "2 小时 5 分" */
  const fmtDuration = (raw, unit) => {
    const n = parseFloat(raw);
    if (!Number.isFinite(n)) return "";
    const neg = n < 0;
    const v = Math.abs(n);
    let out;
    if (unit === "min") {
      const h = Math.floor(v / 60);
      const m = Math.floor(v % 60);
      out = (h ? h + " 小时 " : "") + m + " 分钟";
    } else if (unit === "d") {
      const h = Math.floor(v);
      out = h + " 天 " + Math.floor((v - h) * 24) + " 小时";
    } else {
      const h = Math.floor(v);
      const m = Math.round((v - h) * 60);
      out = (h ? h + " 小时 " : "") + (m ? m + " 分" : (h ? "" : "0 分钟"));
    }
    return (neg ? "已超时 " : "") + out.trim();
  };

  /** 扫地机状态 -> 中文文案（HA 自带翻译对第三方 vacuum 集成常失效） */
  const VAC_STATES = {
    docked: "已停靠", charging: "充电中", charging_complete: "充电完成",
    cleaning: "清扫中", paused: "已暂停", idle: "待机",
    returning: "返回基站", returning_home: "返回基站",
    docking: "对接基站", going_to_target: "前往目标",
    spot_cleaning: "区域清扫", zoned_cleaning: "区域清扫", segment_cleaning: "分区清扫",
    emptying_the_bin: "集尘中", washing_the_mop: "清洗拖布",
    going_to_wash_the_mop: "前往清洗拖布", error: "故障",
    device_offline: "设备离线", unavailable: "不可用",
  };

  const fmtState = (hass, o) => {
    if (!o) return "";
    const raw = o.state;
    if (o.entity_id && String(o.entity_id).indexOf("vacuum.") === 0 && VAC_STATES[raw]) {
      return VAC_STATES[raw];
    }
    // 时间戳类实体（device_class=timestamp）
    const dc = o.attributes ? o.attributes.device_class : "";
    if (dc === "timestamp") {
      const t = fmtTime(raw);
      if (t) return t;
    }
    // 时长类实体（device_class=duration，单位 h/min/d）
    if (dc === "duration") {
      const unit = o.attributes ? o.attributes.unit_of_measurement : "";
      const d = fmtDuration(raw, unit);
      if (d) return d;
    }
    // select 实体：优先用 options 列表把枚举翻译成友好名
    if (o.attributes && Array.isArray(o.attributes.options) && o.attributes.options.length) {
      const opt = o.attributes.options.find((x) =>
        typeof x === "string" ? x === raw : x && x.value === raw);
      if (opt) {
        if (typeof opt === "object" && opt.label) return opt.label;
        const key = String(raw);
        return ENUM_LABELS[key] || key;
      }
    }
    try {
      if (hass && typeof hass.formatEntityState === "function") {
        // 枚举型传感器：先用本地词表翻译（如 Fully -> 电量充足）
        if (dc === "enum" && ENUM_LABELS[String(raw)]) return ENUM_LABELS[String(raw)];
        return hass.formatEntityState(o);
      }
    } catch (e) {
      /* ignore */
    }
    return ENUM_LABELS[String(raw)] || raw;
  };

  const unitOf = (o) => (o && o.attributes ? o.attributes.unit_of_measurement || "" : "");

  const num = (v) => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : null;
  };

  /** 设备图片：配置优先，其次实体自带 entity_picture */
  const picOf = (cfg, hass) => {
    if (cfg.image) return cfg.image;
    const o = obj(hass, cfg.entity);
    if (o && o.attributes && o.attributes.entity_picture) return o.attributes.entity_picture;
    return "";
  };

  const accentOf = (cfg) => cfg.accent || DEFAULT_ACCENT;

  /* ------------------------------------------------------------ 通用样式块 */

  const BASE_CSS = `
    :host { display: block; width: 100%; position: relative; }
    * { box-sizing: border-box; }

    /* ------------------------------------------------------------------
       米家版式（实测参考图：卡片宽高比 ≈ 1.43:1 横向）
         左上 = 产品实物图      右上 = 圆形图标按钮
         左下 = 名称(粗体大号)   ↓   区域 | 状态(灰色小字)
       内部所有尺寸用 cqh（容器高度百分比）随卡片等比缩放，
       保证任何屏幕下卡片内部结构完全一致 —— 不参差。
    ------------------------------------------------------------------ */
    .mi-card {
      position: absolute; inset: 0;
      container-type: size;
      display: block;
      background: var(--ha-card-background, var(--card-background-color, #fff));
      border-radius: var(--ha-card-border-radius, 20px);
      box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,.09));
      overflow: hidden;
      cursor: pointer;
      transition: transform .15s ease, box-shadow .15s ease;
      color: var(--primary-text-color, #212121);
    }
    .mi-card:active { transform: scale(.985); }

    /* 左上角产品图 */
    .mi-media {
      position: absolute;
      left: 14px; top: 16px;
      width: 76px; height: 76px;
      display: flex; align-items: center; justify-content: center;
    }
    .mi-media img {
      max-width: 100%; max-height: 100%;
      width: auto; height: auto;
      object-fit: contain;
      filter: drop-shadow(0 4px 10px rgba(0,0,0,.14));
      transition: filter .2s ease;
    }
    .mi-card.on .mi-media img { filter: drop-shadow(0 4px 14px rgba(255,140,40,.45)); }
    .mi-card.offline .mi-media img { filter: grayscale(1) opacity(.55); }

    /* 右上角圆形图标按钮（米家样式：灰底深色图标 / 开启时主题色底白图标） */
    .mi-btn {
      position: absolute; top: 14px; right: 14px;
      width: 40px; height: 40px; border-radius: 50%;
      background: rgba(140,140,150,.18);
      border: none; padding: 0; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      color: var(--secondary-text-color, #6b6b6b);
      transition: background .2s ease, color .2s ease, box-shadow .2s ease;
      z-index: 2;
    }
    .mi-btn ha-icon { --mdc-icon-size: 21px; }
    .mi-btn:hover { background: rgba(140,140,150,.28); }
    .mi-btn.on {
      background: var(--mi-accent);
      color: #fff;
      box-shadow: 0 4px 12px rgba(255,106,0,.35);
    }

    /* 左下角文字区：固定两行（名称 + 区域|状态），超出省略号 —— 所有卡片等高 */
    .mi-info {
      position: absolute;
      left: 16px; right: 16px; bottom: 14px;
    }
    .mi-name {
      font-size: 15px; font-weight: 600; line-height: 1.35;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .mi-sub {
      font-size: 12.5px; color: var(--secondary-text-color, #6b6b6b); margin-top: 3px;
      display: flex; align-items: center; gap: 6px; min-width: 0;
    }
    .mi-sub .mi-txt { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .mi-sub .mi-area { flex: none; white-space: nowrap; }
    .mi-sub .mi-sep { flex: none; opacity: .45; }
    .mi-sub .mi-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--mi-accent); flex: none; }
    .mi-sub.off .mi-dot { background: rgba(120,120,128,.45); }
    .mi-badge {
      position: absolute; top: 10px; left: 10px;
      font-size: 11px; padding: 2px 7px; border-radius: 10px;
      background: var(--mi-accent); color: #fff; font-weight: 600;
    }
    .mi-card.offline .mi-name { color: var(--secondary-text-color, #8a8a8a); }

    /* 支持容器查询单位时：几何尺寸随卡片高度等比缩放 */
    @supports (height: 1cqh) {
      .mi-media {
        left: 6cqh; top: 7cqh;
        width: 40cqh; height: 40cqh;
      }
      .mi-btn {
        top: 7cqh; right: 6cqh;
        width: 26cqh; height: 26cqh;
      }
      .mi-btn ha-icon { --mdc-icon-size: 13cqh; }
      .mi-info {
        left: 9cqh; right: 9cqh; bottom: 8cqh;
      }
      /* 字号 = 随卡片缩放，但设上下限保证可读 */
      .mi-name { font-size: clamp(12.5px, 10cqh, 19px); }
      .mi-sub { font-size: clamp(11px, 7cqh, 14px); margin-top: 1.6cqh; gap: 2.4cqh; }
      .mi-sub .mi-dot { width: 3.6cqh; height: 3.6cqh; }
    }
  `;

  /* --------------------------------------------------------- 设备小卡片 */

  class MiDeviceCard extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._hass = null;
      this._sig = null;
      this._forceOn = null;   // 红外设备的乐观开关状态
      this._root = this.shadowRoot;
      this._style = document.createElement("style");
      this._style.textContent = BASE_CSS;
      this._root.appendChild(this._style);
      this._box = document.createElement("div");
      this._root.appendChild(this._box);
    }

    setConfig(config) {
      if (!config || !config.entity) {
        throw new Error("请指定 entity");
      }
      this._config = Object.assign({}, config);
      this._sig = null;
      this._render(true);
    }

    set hass(hass) {
      this._hass = hass;
      this._render(false);
    }

    getCardSize() {
      // masonry 中数值越小越容易排成多列
      return 1;
    }

    getGridOptions() {
      // HA sections/grid 的实际规则（已从 2026.11 前端 bundle 反推）：
      //   section 内部栅格列数 = 12 × --column-span（--column-span = section 的 column_span）
      //   每行卡片数 = 内部栅格列数 ÷ 卡片 columns
      //   注意：2026.11 前端会用 min_columns 覆盖 columns，所以真正生效的是 min_columns。
      //   例：min_columns=6 + section column_span=2 -> 桌面 24/6=4 张，手机 12/6=2 张。
      // rows 用 "auto" 让网格按内容自然撑高，避免固定行高把卡片文字挤出可视区。
      const c = this._config || {};
      const cols = Number(c.columns) || 6;
      const minCols = Number(c.min_columns) || cols;
      return {
        columns: cols,
        rows: c.rows || "auto",
        min_columns: minCols,
        min_rows: Number(c.min_rows) || 1,
      };
    }

    _signature() {
      const cfg = this._config;
      const hass = this._hass;
      const st = obj(hass, cfg.entity);
      const sub = cfg.sub_entity ? obj(hass, cfg.sub_entity) : null;
      const sw = cfg.switch_entity ? obj(hass, cfg.switch_entity) : null;
      return [
        st ? st.state : "-",
        st && st.attributes ? st.attributes.entity_picture || "" : "",
        sub ? sub.state : "",
        sw ? sw.state : "",
        cfg.name || "",
        cfg.group || "",
      ].join("|");
    }

    /** 右上角按钮图标：扫地机用小扫把，其余开关类用电源图标 */
    _btnIcon() {
      const cfg = this._config || {};
      if (cfg.btn_icon) return cfg.btn_icon;
      const eid = cfg.switch_entity || cfg.entity || "";
      const domain = eid.split(".")[0];
      if (domain === "vacuum") return "mdi:broom";
      if (domain === "fan") return "mdi:fan";
      if (domain === "light") return "mdi:lightbulb";
      if (domain === "climate" || domain === "water_heater") return "mdi:thermostat";
      if (domain === "media_player") return "mdi:play";
      return "mdi:power";
    }

    _render(force) {
      if (!this._config) return;
      const sig = this._signature();
      if (!force && sig === this._sig) return;
      this._sig = sig;

      const cfg = this._config;
      const hass = this._hass;
      const st = obj(hass, cfg.entity);
      const name = cfg.name || (st && st.attributes.friendly_name) || cfg.entity;
      const pic = picOf(cfg, hass);
      const swEntity = cfg.switch_entity || cfg.entity;
      const swObj = obj(hass, swEntity);
      const domain = swEntity.split(".")[0];
      // 动作型按钮（红外设备的开关机）：没有开关状态，用内部乐观状态
      const actOn = cfg.action_entity || null;
      const actOff = cfg.action_entity_off || null;
      const actionMode = !!actOn;
      const switchable = actionMode ||
        ["switch", "light", "input_boolean", "fan", "climate", "water_heater", "vacuum", "media_player"].includes(domain);
      let on;
      if (actionMode) {
        on = this._forceOn === true;
      } else {
        on = switchable ? isOn(hass, swEntity) : false;
      }
      const accent = accentOf(cfg);

      let stateText = cfg.state_label || fmtState(hass, st);
      // 事件类实体（无线按键触发）显示触发时刻，而不是一大串日期
      if (!cfg.state_label && st && String(cfg.entity).indexOf("event.") === 0) {
        const t = fmtTime(st.state);
        stateText = t ? `触发于 ${t.slice(11, 16)}` : "无触发记录";
      }
      if (cfg.sub_entity) {
        const sub = obj(hass, cfg.sub_entity);
        if (sub) {
          const v = num(sub.state);
          const u = unitOf(sub);
          stateText = v !== null ? `${v}${u}` : fmtState(hass, sub);
        }
      }
      if (on && cfg.on_state_label) stateText = cfg.on_state_label;
      if (!on && cfg.off_state_label) stateText = cfg.off_state_label;

      const offline = st && st.state === "unavailable";
      // 区域标签：只在「全屋」列表显示；区域分类视图里不重复显示
      const area = cfg.group && cfg.show_area !== false
        ? `<span class="mi-area">${esc(cfg.group)}</span><span class="mi-sep">|</span>`
        : "";

      this._box.innerHTML = `
        <div class="mi-card ${on ? "on" : ""} ${offline ? "offline" : ""}" style="--mi-accent:${accent}">
          <div class="mi-media">
            ${pic ? `<img alt="${esc(name)}" src="${esc(pic)}" />` : ""}
          </div>
          ${cfg.badge ? `<div class="mi-badge">${esc(cfg.badge)}</div>` : ""}
          ${switchable ? `<button class="mi-btn ${on ? "on" : ""}" type="button"
                  role="switch" aria-checked="${on}" title="${on ? "关闭" : "开启"}">
                  <ha-icon icon="${esc(this._btnIcon())}"></ha-icon>
                </button>` : ""}
          <div class="mi-info">
            <div class="mi-name" title="${esc(name)}">${esc(name)}</div>
            <div class="mi-sub ${on ? "" : "off"}"><span class="mi-dot"></span>${area}<span class="mi-txt" title="${esc(stateText)}">${esc(stateText)}</span></div>
          </div>
        </div>`;

      const sw = this._box.querySelector(".mi-btn");
      if (sw) {
        sw.addEventListener("click", (ev) => {
          ev.stopPropagation();
          ev.preventDefault();
          if (actOn) {
            // 红外设备：按当前状态选择开机/关机按钮
            const target = this._forceOn && actOff ? actOff : actOn;
            hass.callService(cfg.action_service || "button", "press", { entity_id: target });
            this._forceOn = !this._forceOn;
            this._render(true);
            return;
          }
          this._toggle(swEntity);
        });
      }

      this._box.querySelector(".mi-card").addEventListener("click", () => {
        if (cfg.detail_path) navigate(cfg.detail_path);
        else if (cfg.open_detail && cfg.device_id) fireEvent(this, "mi-card-detail", { deviceId: cfg.device_id });
        else if (cfg.entity) fireEvent(this, "hass-more-info", { entityId: cfg.entity });
      });
    }

    _toggle(entity) {
      const hass = this._hass;
      const id = entity || (this._config ? this._config.entity : null);
      if (!hass || !id) return;
      const domain = id.split(".")[0];
      // 扫地机：正在清扫 -> 暂停；其余（待机/停靠/暂停）-> 开始清扫
      if (domain === "vacuum") {
        const st = obj(hass, id);
        const s = st ? st.state : "";
        if (VAC_ACTIVE.has(s)) hass.callService("vacuum", "pause", { entity_id: id });
        else hass.callService("vacuum", "start", { entity_id: id });
        return;
      }
      hass.callService(domain, "toggle", { entity_id: id });
    }
  }

  /* --------------------------------------------------------- 设备详情页 */

  const DETAIL_CSS = `
    :host { display: block; }
    * { box-sizing: border-box; }
    .mi-d { color: var(--primary-text-color, #212121); }
    .mi-wrap { max-width: 520px; margin: 0 auto; width: 100%; }
    .mi-top { display: flex; align-items: center; gap: 10px; padding: 4px 2px 14px; }
    .mi-back {
      width: 36px; height: 36px; border-radius: 50%; border: none; cursor: pointer;
      background: var(--secondary-background-color, rgba(120,120,128,.16));
      color: var(--primary-text-color, #212121); font-size: 18px; line-height: 1;
      display: flex; align-items: center; justify-content: center;
    }
    .mi-top-title { font-size: 17px; font-weight: 600; }
    .mi-top-sub { font-size: 12.5px; color: var(--secondary-text-color, #8a8a8a); margin-top: 2px; }

    .mi-hero { display: flex; flex-direction: column; align-items: center; padding: 6px 0 18px; }
    .mi-hero.with-gauge { flex-direction: row; justify-content: center; gap: 18px; align-items: center; }
    .mi-hero-img {
      width: 132px; height: 132px; object-fit: contain;
      background: var(--mi-card-bg, radial-gradient(circle at 50% 38%, #ffffff 0%, #f2f3f5 70%, #eceef1 100%));
      border-radius: 16px; padding: 8px; box-sizing: border-box;
    }
    .mi-hero:not(.with-gauge) .mi-hero-img { width: 176px; height: 176px; }
    @media (max-width: 420px) {
      .mi-hero.with-gauge { flex-direction: column; gap: 12px; }
      .mi-hero-img { width: 116px; height: 116px; }
    }
    .mi-gauge {
      width: 210px; height: 210px; border-radius: 50%;
      background: var(--mi-gauge-bg, radial-gradient(circle at 50% 30%, #ffd9a8 0%, #ffb570 45%, #ff9a3c 100%));
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      color: #fff; box-shadow: 0 10px 26px rgba(255,140,60,.28);
    }
    .mi-gauge-label { font-size: 13px; opacity: .95; }
    .mi-gauge-value { font-size: 62px; font-weight: 300; line-height: 1.05; letter-spacing: -1px; }
    .mi-gauge-value .u { font-size: 20px; margin-left: 2px; }
    .mi-gauge-status { font-size: 15px; font-weight: 500; margin-top: 2px; }

    .mi-block {
      background: var(--ha-card-background, var(--card-background-color, #fff));
      border-radius: var(--ha-card-border-radius, 18px);
      box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.06));
      padding: 14px 16px; margin-bottom: 12px;
    }
    .mi-block-title { font-size: 15px; font-weight: 600; display: flex; align-items: baseline; gap: 8px; }
    .mi-block-sub { font-size: 13px; color: var(--secondary-text-color, #8a8a8a); font-weight: 400; }

    .mi-row {
      display: flex; align-items: center; gap: 12px;
      background: var(--ha-card-background, var(--card-background-color, #fff));
      border-radius: var(--ha-card-border-radius, 16px);
      box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.06));
      padding: 14px 16px; margin-bottom: 12px;
      min-height: 58px;
    }
    .mi-row.clickable { cursor: pointer; }
    .mi-row-icon {
      width: 34px; height: 34px; border-radius: 50%; flex: none;
      display: flex; align-items: center; justify-content: center;
      background: var(--mi-accent-soft, rgba(255,106,0,.14)); color: var(--mi-accent, #ff6a00);
    }
    .mi-row-icon ha-icon { --mdc-icon-size: 20px; }
    .mi-row-main { flex: 1; min-width: 0; }
    .mi-row-title { font-size: 15px; }
    .mi-row-sub { font-size: 12px; color: var(--secondary-text-color, #8a8a8a); margin-top: 2px; }
    .mi-row-value { font-size: 14px; color: var(--secondary-text-color, #8a8a8a); white-space: nowrap; }
    .mi-chevron { font-size: 20px; color: var(--secondary-text-color, #b0b0b0); }

    .mi-switch-sm {
      width: 46px; height: 27px; border-radius: 14px; border: none; padding: 0; cursor: pointer;
      background: rgba(120,120,128,.28); display: flex; align-items: center; flex: none;
      transition: background .2s ease;
    }
    .mi-switch-sm .mi-knob {
      width: 21px; height: 21px; border-radius: 50%; background: #fff; margin-left: 3px;
      box-shadow: 0 1px 3px rgba(0,0,0,.3); transition: transform .2s cubic-bezier(.3,1.4,.6,1);
    }
    .mi-switch-sm.on { background: var(--mi-accent, #ff6a00); }
    .mi-switch-sm.on .mi-knob { transform: translateX(19px); }

    .mi-seg { display: flex; gap: 10px; margin-top: 14px; }
    .mi-seg-btn {
      flex: 1; border: none; cursor: pointer; border-radius: 50%;
      width: 58px; height: 58px; margin: 0 auto; font-size: 19px; font-weight: 500;
      background: rgba(120,120,128,.16); color: var(--secondary-text-color, #8a8a8a);
      display: flex; align-items: center; justify-content: center;
      transition: background .18s ease, color .18s ease, transform .12s ease;
    }
    .mi-seg-btn .sub { display: block; font-size: 11px; margin-top: 2px; font-weight: 400; }
    .mi-seg-btn.sel {
      background: var(--mi-accent, #ff6a00); color: #fff;
      box-shadow: 0 4px 14px rgba(255,106,0,.35);
    }
    .mi-seg-wrap { display: flex; gap: 10px; }
    .mi-seg-item { flex: 1; display: flex; flex-direction: column; align-items: center; }
    .mi-seg-label { font-size: 12px; color: var(--secondary-text-color, #8a8a8a); margin-top: 6px; }
    .mi-seg-label.sel { color: var(--mi-accent, #ff6a00); }

    .mi-power {
      display: flex; align-items: center; gap: 12px; cursor: pointer;
      background: var(--ha-card-background, var(--card-background-color, #fff));
      border-radius: var(--ha-card-border-radius, 16px);
      box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.06));
      padding: 16px; margin-bottom: 12px;
    }
    .mi-power.on .mi-row-icon { background: var(--mi-accent, #ff6a00); color: #fff; }

    .mi-select {
      appearance: none; -webkit-appearance: none;
      background: rgba(120,120,128,.14); border: none; border-radius: 10px;
      padding: 7px 12px; font-size: 14px; color: var(--primary-text-color, #212121);
    }
    .mi-range { width: 100%; accent-color: var(--mi-accent, #ff6a00); }
    .mi-btn {
      border: none; border-radius: 10px; padding: 8px 16px; font-size: 14px; cursor: pointer;
      background: var(--mi-accent, #ff6a00); color: #fff; font-weight: 500;
    }
    .mi-btn.ghost { background: rgba(120,120,128,.16); color: var(--primary-text-color, #212121); }
    .mi-sec-title { font-size: 13px; color: var(--secondary-text-color, #8a8a8a); margin: 14px 2px 8px; }
  `;

  class MiDeviceDetail extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._hass = null;
      this._sig = null;
      this._root = this.shadowRoot;
      this._style = document.createElement("style");
      this._style.textContent = DETAIL_CSS;
      this._root.appendChild(this._style);
      this._box = document.createElement("div");
      this._box.className = "mi-d";
      this._root.appendChild(this._box);
    }

    setConfig(config) {
      this._config = Object.assign({ entities: [] }, config || {});
      this._sig = null;
      this._render(true);
    }

    set hass(hass) {
      this._hass = hass;
      this._render(false);
    }

    getCardSize() {
      return 6;
    }

    getGridOptions() {
      // "full" -> 卡片撑满 section 整宽，内部 .mi-wrap 再按 520px 居中
      return { columns: "full", rows: "auto", min_columns: 12, min_rows: 1 };
    }

    _signature() {
      const cfg = this._config;
      const hass = this._hass;
      const parts = [cfg.title || "", cfg.gauge ? cfg.gauge.entity : ""];
      if (cfg.gauge && cfg.gauge.entity) {
        const g = obj(hass, cfg.gauge.entity);
        parts.push(g ? g.state : "-");
      }
      if (cfg.gauge && cfg.gauge.status_entity) {
        const s = obj(hass, cfg.gauge.status_entity);
        parts.push(s ? s.state : "-");
      }
      if (cfg.power) {
        const p = obj(hass, cfg.power.entity);
        parts.push(p ? p.state : "-");
      }
      (cfg.choices || []).forEach((c) => {
        const o = obj(hass, c.entity);
        parts.push(o ? o.state : "-");
      });
      (cfg.entities || []).forEach((e) => {
        const o = obj(hass, e.entity);
        parts.push(o ? o.state : "-");
      });
      return parts.join("|");
    }

    _render(force) {
      if (!this._config) return;
      const sig = this._signature();
      if (!force && sig === this._sig) return;
      this._sig = sig;

      const cfg = this._config;
      const hass = this._hass;
      const accent = accentOf(cfg);
      const parts = [];

      /* 顶部 */
      parts.push(`
        <div class="mi-top">
          <button class="mi-back" type="button" title="返回">‹</button>
          <div>
            <div class="mi-top-title">${esc(cfg.title || "")}</div>
            ${cfg.subtitle ? `<div class="mi-top-sub">${esc(cfg.subtitle)}</div>` : ""}
          </div>
        </div>`);

      /* 大温度圈 */
      if (cfg.gauge && cfg.gauge.entity) {
        const g = obj(hass, cfg.gauge.entity);
        const raw = cfg.gauge.value_attribute
          ? (g && g.attributes ? g.attributes[cfg.gauge.value_attribute] : null)
          : g ? g.state : null;
        const v = num(raw);
        const u = g && unitOf(g) ? unitOf(g) : cfg.gauge.unit || "";
        let status = "";
        if (cfg.gauge.status_entity) {
          const s = obj(hass, cfg.gauge.status_entity);
          if (s) {
            status = fmtState(hass, s);
            const map = cfg.gauge.status_map || {};
            if (map[s.state]) status = map[s.state];
          }
        }
        // 实物图：有温度圈时并排显示（大图+温度圈），没有则单独一行居中
        const heroImg = cfg.image
          ? `<img class="mi-hero-img" src="${esc(cfg.image)}" alt="" loading="lazy" />`
          : "";
        parts.push(`
          <div class="mi-hero ${cfg.gauge ? "with-gauge" : ""}">
            ${heroImg}
            ${cfg.gauge ? `
            <div class="mi-gauge" style="--mi-gauge-bg:${cfg.gauge.bg || "radial-gradient(circle at 50% 30%, #ffd9a8 0%, #ffb570 45%, #ff9a3c 100%)"}">
              <div class="mi-gauge-label">${esc(cfg.gauge.label || "当前温度")} (${esc(u)})</div>
              <div class="mi-gauge-value">${v === null ? "--" : v}<span class="u">${esc(u)}</span></div>
              <div class="mi-gauge-status">${esc(status)}</div>
            </div>` : ""}
          </div>`);
      } else if (cfg.image) {
        parts.push(`
          <div class="mi-hero">
            <img class="mi-hero-img" src="${esc(cfg.image)}" alt="" loading="lazy" />
          </div>`);
      }

      /* 开关 / 电源 */
      if (cfg.power && cfg.power.entity) {
        const p = obj(hass, cfg.power.entity);
        const on = isOn(hass, cfg.power.entity);
        const label = on
          ? cfg.power.on_label || "关机"
          : cfg.power.off_label || "开机";
        parts.push(`
          <div class="mi-power ${on ? "on" : ""}" data-role="power">
            <div class="mi-row-icon"><ha-icon icon="${on ? "mdi:power" : "mdi:power"}"></ha-icon></div>
            <div class="mi-row-main"><div class="mi-row-title">${esc(label)}</div></div>
          </div>`);
      }

      /* 档位选择 */
      (cfg.choices || []).forEach((c, ci) => {
        const o = obj(hass, c.entity);
        const cur = o ? o.state : "";
        // 优先读 operation_mode 属性（water_heater 等设备 state 可能是 off，而档位在属性里）
        const attrCur =
          c.value_key && o && o.attributes ? o.attributes[c.value_key] : undefined;
        const active = attrCur !== undefined && attrCur !== null ? attrCur : cur;
        const opts = c.options || (o && o.attributes ? o.attributes.options || [] : []);
        const btns = opts
          .map((raw) => {
            const opt = typeof raw === "object" ? raw : { value: raw };
            const sel = String(opt.value) === String(active);
            const label = opt.label || opt.value;
            // 圆钮里只放主标（L/M/H），档位文字放在下方一行，避免重复
            return `<div class="mi-seg-item">
                <button class="mi-seg-btn ${sel ? "sel" : ""}" data-value="${esc(opt.value)}" data-choice="${ci}" type="button">${esc(label)}</button>
                <div class="mi-seg-label ${sel ? "sel" : ""}">${esc(opt.sub || "")}</div>
              </div>`;
          })
          .join("");
        const curLabel = opts.length
          ? (opts.find((r) => String(typeof r === "object" ? r.value : r) === String(active)) || {})
          : {};
        const curText = typeof curLabel === "object" ? curLabel.sub || curLabel.label || "" : "";
        parts.push(`
          <div class="mi-block">
            <div class="mi-block-title">${esc(c.title || "")}<span class="mi-block-sub">${esc(curText)}</span></div>
            <div class="mi-seg">${btns}</div>
          </div>`);
      });

      /* 其它常用功能 */
      const ents = cfg.entities || [];
      if (ents.length) {
        const rows = ents.map((e) => this._renderRow(e)).join("");
        parts.push(`<div class="mi-sec-title">常用功能</div>${rows}`);
      }

      this._box.innerHTML = `<div class="mi-wrap" style="--mi-accent:${accent}">${parts.join("")}</div>`;

      /* 事件绑定 */
      const back = this._box.querySelector(".mi-back");
      if (back) {
        back.addEventListener("click", () => {
          if (cfg.close_on_back) {
            fireEvent(this, "mi-detail-close", {});
            return;
          }
          if (window.history.length > 1) window.history.back();
          else navigate(cfg.back_path || "/");
        });
      }
      const power = this._box.querySelector('[data-role="power"]');
      if (power && cfg.power) {
        power.addEventListener("click", () => this._toggle(cfg.power.entity));
      }
      this._box.querySelectorAll(".mi-seg-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const group = (cfg.choices || [])[Number(btn.dataset.choice)];
          if (!group || !group.entity) return;
          this._select(group.entity, btn.dataset.value, group.service, group.value_key);
        });
      });
      this._box.querySelectorAll("[data-select]").forEach((sel) => {
        sel.addEventListener("change", () => this._select(sel.dataset.select, sel.value));
      });
      this._box.querySelectorAll("[data-range]").forEach((rng) => {
        rng.addEventListener("change", () => {
          const hass2 = this._hass;
          if (!hass2) return;
          hass2.callService("number", "set_value", {
            entity_id: rng.dataset.range,
            value: Number(rng.value),
          });
        });
      });
      this._box.querySelectorAll("[data-toggle]").forEach((sw) => {
        sw.addEventListener("click", (ev) => {
          ev.stopPropagation();
          this._toggle(sw.dataset.toggle);
        });
      });
      this._box.querySelectorAll("[data-number-switch]").forEach((sw) => {
        sw.addEventListener("click", (ev) => {
          ev.stopPropagation();
          const hass2 = this._hass;
          const o = obj(hass2, sw.dataset.numberSwitch);
          const cur = o ? num(o.state) || 0 : 0;
          const next = cur > 0 ? 0 : 1;
          hass2.callService("number", "set_value", {
            entity_id: sw.dataset.numberSwitch,
            value: next,
          });
        });
      });
      this._box.querySelectorAll("[data-press]").forEach((b) => {
        b.addEventListener("click", (ev) => {
          ev.stopPropagation();
          this._press(b.dataset.press);
        });
      });
      this._box.querySelectorAll("[data-more]").forEach((r) => {
        r.addEventListener("click", () => fireEvent(this, "hass-more-info", { entityId: r.dataset.more }));
      });
    }

    _renderRow(e) {
      const cfg = this._config;
      const hass = this._hass;
      const o = obj(hass, e.entity);
      const domain = e.entity.split(".")[0];
      const title = e.name || (o && o.attributes ? o.attributes.friendly_name : "") || e.entity;
      const icon = e.icon || this._defaultIcon(domain);
      const sub = e.sub || "";

      let right = "";
      if (domain === "switch" || domain === "light" || domain === "input_boolean" || domain === "fan") {
        const on = isOn(hass, e.entity);
        right = `<button class="mi-switch-sm ${on ? "on" : ""}" type="button" role="switch"
                  aria-checked="${on}" data-toggle="${esc(e.entity)}"><span class="mi-knob"></span></button>`;
      } else if (domain === "select") {
        const cur = o ? o.state : "";
        right = `<select class="mi-select" data-select="${esc(e.entity)}">
          ${(o && o.attributes ? o.attributes.options || [] : [])
            .map((v) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${esc(ENUM_LABELS[String(v)] || v)}</option>`)
            .join("")}
        </select>`;
      } else if (domain === "number" && e.as_switch) {
        const on = (num(o ? o.state : 0) || 0) > 0;
        right = `<button class="mi-switch-sm ${on ? "on" : ""}" type="button" role="switch"
                  aria-checked="${on}" data-number-switch="${esc(e.entity)}"><span class="mi-knob"></span></button>`;
      } else if (domain === "number") {
        const v = o ? o.state : "";
        const min = o && o.attributes ? o.attributes.min : 0;
        const max = o && o.attributes ? o.attributes.max : 100;
        const step = o && o.attributes ? o.attributes.step || 1 : 1;
        right = `<div style="display:flex;align-items:center;gap:8px">
            <input class="mi-range" type="range" min="${min}" max="${max}" step="${step}" value="${esc(v)}" data-range="${esc(e.entity)}" />
            <span class="mi-row-value">${esc(v)}${esc(unitOf(o))}</span>
          </div>`;
      } else if (domain === "button" || domain === "input_button") {
        right = `<button class="mi-btn" type="button" data-press="${esc(e.entity)}">${esc(e.action_label || "执行")}</button>`;
      } else if (o) {
        const v = num(o.state);
        right = `<span class="mi-row-value">${esc(v !== null ? v + unitOf(o) : fmtState(hass, o))}</span>`;
      }

      const more = e.more_info === false ? "" : ` data-more="${esc(e.entity)}"`;
      return `
        <div class="mi-row clickable"${more}>
          <div class="mi-row-icon"><ha-icon icon="${esc(icon)}"></ha-icon></div>
          <div class="mi-row-main">
            <div class="mi-row-title">${esc(title)}</div>
            ${sub ? `<div class="mi-row-sub">${esc(sub)}</div>` : ""}
          </div>
          ${right}
        </div>`;
    }

    _defaultIcon(domain) {
      const map = {
        switch: "mdi:power",
        light: "mdi:lightbulb",
        input_boolean: "mdi:toggle-switch-outline",
        fan: "mdi:fan",
        sensor: "mdi:eye-outline",
        binary_sensor: "mdi:check-circle-outline",
        number: "mdi:numeric",
        select: "mdi:format-list-bulleted",
        button: "mdi:gesture-tap-button",
        input_button: "mdi:gesture-tap-button",
        climate: "mdi:thermostat",
        water_heater: "mdi:water-boiler",
      };
      return map[domain] || "mdi:help-circle-outline";
    }

    _toggle(entity) {
      const hass = this._hass;
      if (!hass || !entity) return;
      const domain = entity.split(".")[0];
      hass.callService(domain, "toggle", { entity_id: entity });
    }

    _select(entity, value, service, valueKey) {
      const hass = this._hass;
      if (!hass || !entity) return;
      if (service) {
        const parts = service.split(".");
        const domain = parts[0];
        const svc = parts.slice(1).join(".");
        const data = { entity_id: entity };
        data[valueKey || "option"] = value;
        hass.callService(domain, svc, data);
        return;
      }
      hass.callService("select", "select_option", { entity_id: entity, option: value });
    }

    _press(entity) {
      const hass = this._hass;
      if (!hass || !entity) return;
      const domain = entity.split(".")[0];
      hass.callService(domain, "press", { entity_id: entity });
    }
  }

  /* ---------------------------------------------- 设备网格（区域分类由 HA 视图菜单负责） */

  const WALL_CSS = `
    :host { display: block; }
    * { box-sizing: border-box; }
    .mi-wall { color: var(--primary-text-color, #212121); }

    /* 网格：卡片宽度固定（不随全屏拉伸），列数随视口自适应 */
    .mi-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, 260px);
      justify-content: center;
      gap: 16px;
      align-items: start;
    }
    .mi-grid > mi-device-card { min-width: 0; }

    /* 卡片固定米家比例（实测参考图 ≈ 1.43:1 横向），宽度锁定后高度自然得出 */
    .mi-grid > mi-device-card { aspect-ratio: 1.43 / 1; }

    @media (max-width: 1100px) {
      .mi-grid { grid-template-columns: repeat(auto-fill, 230px); gap: 14px; }
    }
    @media (max-width: 700px) {
      /* 移动端两列；限制整体宽度，避免大屏手机/横屏时卡片被拉得过大 */
      .mi-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px; max-width: 560px; margin: 0 auto;
      }
    }
    @media (max-width: 420px) {
      .mi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    }
  `;

  class MiAreaWall extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._hass = null;
      this._active = "all";
      this._root = this.shadowRoot;
      this._style = document.createElement("style");
      this._style.textContent = WALL_CSS;
      this._root.appendChild(this._style);
      this._box = document.createElement("div");
      this._box.className = "mi-wall";
      this._root.appendChild(this._box);
    }

    setConfig(config) {
      this._config = Object.assign({ cards: [] }, config || {});
      this._render(true);
    }

    set hass(hass) {
      this._hass = hass;
      this._render(false);
    }

    getCardSize() {
      return 12;
    }

    getGridOptions() {
      // 整块占满 section 宽度，内部自己排网格
      return { columns: "full", rows: "auto", min_columns: 12, min_rows: 1 };
    }

    _render(force) {
      if (!this._config) return;
      const cfg = this._config;
      const cards = cfg.cards || [];
      const accent = accentOf(cfg);

      // 首次渲染建 DOM，之后只推 hass（保留卡片状态，避免闪烁）
      if (force || !this._built) {
        this._box.innerHTML = `<div class="mi-grid"></div>`;

        const grid = this._box.querySelector(".mi-grid");
        for (const c of cards) {
          const el = document.createElement("mi-device-card");
          el.setConfig(Object.assign({}, c));
          if (this._hass) el.hass = this._hass;
          grid.appendChild(el);
        }
        this._built = true;
      } else {
        const grid = this._box.querySelector(".mi-grid");
        grid.querySelectorAll("mi-device-card").forEach((el) => {
          if (this._hass) el.hass = this._hass;
        });
      }

      this._box.style.setProperty("--mi-accent", accent);
    }
  }

  /* ------------------------------------------------- 动态区域墙（集成版） */

  /**
   * custom:mi-device-wall
   *
   * 与 mi-area-wall 的区别：卡片内容不写死在 YAML 里，而是运行时从 HA 进程内
   * 拉设备树（WebSocket 命令 mi_cards/device_tree）。房间/设备增删改名后，
   * 服务端会推 mi_cards/tree_updated 事件，前端据此自动重建 —— 无需改配置。
   *
   * 配置项：
   *   area       限定某个区域（区域 id 或名称）。给了就不显示区域标签栏
   *   accent     主色，默认 #ff6a00
   *   columns    卡片宽度（px），默认 260
   *   show_area  卡片副标题里是否显示「区域 | 状态」，默认：全屋视图 true、区域视图 false
   *   title      顶部标题（可省略）
   */
  const DEVICE_WALL_CSS = `
    :host { display: block; }
    * { box-sizing: border-box; }
    .mi-dw { color: var(--primary-text-color, #212121); }

    .mi-dw-title {
      font-size: 20px; font-weight: 600; margin: 2px 2px 12px;
    }

    .mi-tabs {
      display: flex; gap: 8px; overflow-x: auto; padding: 2px 2px 16px;
      scrollbar-width: none; -ms-overflow-style: none;
    }
    .mi-tabs::-webkit-scrollbar { display: none; }
    .mi-tab {
      flex: none; display: inline-flex; align-items: center; gap: 6px;
      padding: 8px 15px; border-radius: 999px; cursor: pointer;
      background: var(--secondary-background-color, rgba(120,120,128,.14));
      color: var(--primary-text-color, #212121);
      font-size: 14px; white-space: nowrap; border: none; font-family: inherit;
      transition: background .18s ease, color .18s ease;
    }
    .mi-tab:hover { background: rgba(120,120,128,.24); }
    .mi-tab.active {
      background: var(--mi-accent, #ff6a00); color: #fff;
      box-shadow: 0 4px 14px rgba(255,106,0,.28);
    }
    .mi-tab ha-icon { --mdc-icon-size: 18px; }
    .mi-tab .mi-tab-n { font-size: 12px; opacity: .72; }

    .mi-grid {
      display: grid; gap: 16px; align-items: start; justify-content: center;
      grid-template-columns: repeat(auto-fill, var(--mi-card-w, 260px));
    }
    .mi-grid > mi-device-card { min-width: 0; aspect-ratio: 1.43 / 1; }

    .mi-empty {
      text-align: center; color: var(--secondary-text-color, #8a8a8a);
      padding: 46px 12px; font-size: 14px;
    }
    .mi-err { color: var(--error-color, #db4437); font-size: 13px; padding: 20px 4px; }
  `;

  class MiDeviceWall extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = null;
      this._hass = null;
      this._tree = null;
      this._active = "all";
      this._unsub = null;
      this._overlay = null;
      this._esc = null;
      this._pullTimer = null;

      this._style = document.createElement("style");
      this._style.textContent = DEVICE_WALL_CSS;
      this.shadowRoot.appendChild(this._style);
      this._box = document.createElement("div");
      this._box.className = "mi-dw";
      this.shadowRoot.appendChild(this._box);
    }

    setConfig(config) {
      this._config = Object.assign(
        { accent: DEFAULT_ACCENT, columns: 260 },
        config || {}
      );
      this._scopeRaw = this._config.area || null;
      this._scoped = null;
      this._scopeMissing = false;
      this._render();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first) {
        this._subscribe();
        this._pull();
        // 兜底轮询：万一推送事件漏了，最多 2 分钟内也会自我修复
        this._pullTimer = window.setInterval(() => this._pull(), 120000);
      }
      this._pushHass();
    }

    disconnectedCallback() {
      if (this._unsub) {
        try { this._unsub(); } catch (e) { /* noop */ }
        this._unsub = null;
      }
      if (this._pullTimer) {
        window.clearInterval(this._pullTimer);
        this._pullTimer = null;
      }
      this._closeDetail();
    }

    getCardSize() {
      return 12;
    }

    getGridOptions() {
      return { columns: "full", rows: "auto", min_columns: 12, min_rows: 1 };
    }

    /* -------------------------------------------------- 数据 */

    /** 解析区域范围：接受区域 id 或区域名称；"other" 表示未分配区域的设备 */
    _resolveScope(area) {
      if (!area || !this._tree) return null;
      if (area === "other") return "other";
      const areas = this._tree.areas || [];
      const hit = areas.find((a) => a.id === area || a.name === area || a.slug === area);
      return hit ? hit.id : null;
    }

    async _pull() {
      if (!this._hass) return;
      try {
        const tree = await this._hass.callWS({ type: "mi_cards/device_tree" });
        if (!tree) return;
        this._tree = tree;
        if (this._scopeRaw) {
          this._scoped = this._resolveScope(this._scopeRaw);
          this._scopeMissing = !this._scoped;
          if (this._scoped) this._active = this._scoped;
        }
        this._render();
        this._pushHass();
      } catch (err) {
        console.warn("[mi-cards] 设备树拉取失败", err);
        this._box.innerHTML = `<div class="mi-err">设备树拉取失败：${esc(String(err && err.message || err))}</div>`;
      }
    }

    _subscribe() {
      if (this._unsub || !this._hass || !this._hass.connection) return;
      try {
        this._unsub = this._hass.connection.subscribeMessage(
          () => this._pull(),
          { type: "subscribe_events", event_type: "mi_cards/tree_updated" }
        );
      } catch (err) {
        console.warn("[mi-cards] 订阅设备树更新失败", err);
      }
    }

    /* -------------------------------------------------- 渲染 */

    _currentDevices() {
      const tree = this._tree;
      if (!tree) return [];
      if (this._active === "all") {
        const all = [];
        (tree.areas || []).forEach((a) => all.push.apply(all, a.devices || []));
        (tree.other || []).forEach((d) => all.push(d));
        return all;
      }
      if (this._active === "other") return tree.other || [];
      const area = (tree.areas || []).find((a) => a.id === this._active);
      return area ? area.devices || [] : [];
    }

    _render() {
      if (!this._config) return;
      const cfg = this._config;
      const tree = this._tree;
      const accent = accentOf(cfg);

      this._box.style.setProperty("--mi-accent", accent);
      this._box.style.setProperty("--mi-card-w", (Number(cfg.columns) || 260) + "px");

      if (!tree) {
        this._box.innerHTML = `<div class="mi-empty">正在加载设备…</div>`;
        return;
      }

      const areas = tree.areas || [];
      const others = tree.other || [];

      /* 顶部：标题 + 区域标签栏 */
      const parts = [];
      if (cfg.title) parts.push(`<div class="mi-dw-title">${esc(cfg.title)}</div>`);

      if (!this._scopeRaw && cfg.show_tabs !== false) {
        const tabs = [];
        tabs.push(this._tabHtml("all", "mdi:home-outline", "全部", this._countAll(areas, others), this._active === "all"));
        areas.forEach((a) => {
          tabs.push(this._tabHtml(a.id, a.icon || "mdi:sofa", a.name, (a.devices || []).length, this._active === a.id));
        });
        if (others.length) {
          tabs.push(this._tabHtml("other", "mdi:dots-horizontal", "其他", others.length, this._active === "other"));
        }
        parts.push(`<div class="mi-tabs">${tabs.join("")}</div>`);
      }

      if (this._scopeMissing) {
        parts.push(`<div class="mi-empty">没有找到区域「${esc(this._scopeRaw)}」</div>`);
        this._box.innerHTML = parts.join("");
        return;
      }

      const devices = this._currentDevices();
      if (!devices.length) {
        parts.push(`<div class="mi-empty">这个区域还没有设备</div>`);
      } else {
        parts.push(`<div class="mi-grid"></div>`);
      }

      this._box.innerHTML = parts.join("");

      const grid = this._box.querySelector(".mi-grid");
      if (grid) {
        // 全屋视图显示「区域 | 状态」，区域视图只显示状态
        const showArea = cfg.show_area === undefined
          ? this._active === "all"
          : !!cfg.show_area;
        for (const dev of devices) {
          const el = document.createElement("mi-device-card");
          const cardCfg = Object.assign({}, dev.card, {
            open_detail: true,
            device_id: dev.device_id,
            accent,
          });
          if (showArea) {
            cardCfg.group = dev.area || "";
            cardCfg.show_area = true;
          } else {
            cardCfg.show_area = false;
          }
          el.setConfig(cardCfg);
          if (this._hass) el.hass = this._hass;
          grid.appendChild(el);
        }
        grid.addEventListener("mi-card-detail", (ev) => {
          this._openDetail(ev.detail && ev.detail.deviceId);
        });
      }

      /* 标签栏事件 */
      this._box.querySelectorAll(".mi-tab").forEach((btn) => {
        btn.addEventListener("click", () => {
          this._active = btn.dataset.tab;
          this._render();
          this._pushHass();
        });
      });
    }

    _tabHtml(id, icon, name, count, active) {
      return `<button type="button" class="mi-tab ${active ? "active" : ""}" data-tab="${esc(id)}">
        <ha-icon icon="${esc(icon)}"></ha-icon>${esc(name)}<span class="mi-tab-n">${count}</span>
      </button>`;
    }

    _countAll(areas, others) {
      let n = others ? others.length : 0;
      areas.forEach((a) => (n += (a.devices || []).length));
      return n;
    }

    _pushHass() {
      if (!this._hass) return;
      this._box.querySelectorAll("mi-device-card").forEach((el) => {
        el.hass = this._hass;
      });
      if (this._overlay) {
        const detail = this._overlay.querySelector("mi-device-detail");
        if (detail) detail.hass = this._hass;
      }
    }

    /* -------------------------------------------------- 详情浮层 */

    _openDetail(deviceId) {
      if (!this._tree || !deviceId) return;
      const dev = this._tree.devices ? this._tree.devices[deviceId] : null;
      if (!dev) return;
      this._closeDetail();

      const overlay = document.createElement("div");
      overlay.style.cssText = [
        "position:fixed", "inset:0", "z-index:1000",
        "display:flex", "align-items:center", "justify-content:center",
        "padding:16px", "box-sizing:border-box",
        "background:rgba(0,0,0,.55)",
      ].join(";");

      const sheet = document.createElement("div");
      sheet.style.cssText = [
        "background:var(--primary-background-color,#f6f7f9)",
        "border-radius:20px", "width:100%", "max-width:560px",
        "max-height:92vh", "overflow-y:auto", "padding:16px",
        "box-shadow:0 18px 48px rgba(0,0,0,.32)", "box-sizing:border-box",
      ].join(";");

      const detail = document.createElement("mi-device-detail");
      detail.setConfig(Object.assign({}, dev.detail, { close_on_back: true }));
      if (this._hass) detail.hass = this._hass;
      detail.addEventListener("mi-detail-close", () => this._closeDetail());

      sheet.appendChild(detail);
      overlay.appendChild(sheet);
      overlay.addEventListener("click", (ev) => {
        if (ev.target === overlay) this._closeDetail();
      });
      document.body.appendChild(overlay);

      this._overlay = overlay;
      this._esc = (ev) => {
        if (ev.key === "Escape") this._closeDetail();
      };
      window.addEventListener("keydown", this._esc);
    }

    _closeDetail() {
      if (this._overlay) {
        this._overlay.remove();
        this._overlay = null;
      }
      if (this._esc) {
        window.removeEventListener("keydown", this._esc);
        this._esc = null;
      }
    }
  }

  /* ------------------------------------------------------------- 注册 */

  if (!customElements.get("mi-device-card")) {
    customElements.define("mi-device-card", MiDeviceCard);
  }
  if (!customElements.get("mi-device-detail")) {
    customElements.define("mi-device-detail", MiDeviceDetail);
  }
  if (!customElements.get("mi-area-wall")) {
    customElements.define("mi-area-wall", MiAreaWall);
  }
  if (!customElements.get("mi-device-wall")) {
    customElements.define("mi-device-wall", MiDeviceWall);
  }

  window.customCards = window.customCards || [];
  window.customCards.push(
    { type: "mi-device-card", name: "米家设备卡片", description: "实物图 + 右上角开关，点击进入设备详情" },
    { type: "mi-device-detail", name: "米家设备详情", description: "温度圈 / 开关 / 档位 / 常用功能" },
    { type: "mi-area-wall", name: "米家区域墙", description: "区域标签栏 + 响应式设备网格" },
    { type: "mi-device-wall", name: "米家动态设备墙", description: "自动读取 HA 设备树，房间/设备变化实时自适应" }
  );

  console.info("[mi-cards] 自定义卡片已加载");
})();
