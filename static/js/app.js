function countTextLines(value) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean).length;
}

function setActiveTab(target) {
  const sourceInput = document.querySelector("[data-source-input]");
  const triggers = document.querySelectorAll("[data-tab-trigger]");
  const panels = document.querySelectorAll("[data-tab-panel]");

  triggers.forEach((button) => {
    const active = button.dataset.tabTrigger === target;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });

  panels.forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.tabPanel === target);
  });

  if (sourceInput) {
    sourceInput.value = target;
  }
}

async function refreshCountryProfile() {
  const countryInput = document.querySelector("[data-country-input]");
  const prefixInput = document.querySelector("[data-remark-prefix-input]");
  const startInput = document.querySelector("[data-remark-start-input]");
  const prefixLabel = document.querySelector("[data-country-prefix]");
  const metaLabel = document.querySelector("[data-country-meta]");

  if (!countryInput || !prefixInput || !startInput || !prefixLabel || !metaLabel) {
    return;
  }

  const country = countryInput.value.trim();
  if (!country) {
    prefixInput.value = "Proxy-";
    startInput.value = "1";
    prefixLabel.textContent = "Proxy-";
    metaLabel.textContent = "输入国家后，会自动推荐前缀与续号。";
    return;
  }

  try {
    const response = await fetch(`/api/countries/profile?country=${encodeURIComponent(country)}`);
    const data = await response.json();
    prefixInput.value = data.suggested_prefix || `${country}电商`;
    startInput.value = String(data.next_number || 1);
    prefixLabel.textContent = `${prefixInput.value}${startInput.value}`;
    metaLabel.textContent =
      data.record_count > 0
        ? `当前已有 ${data.record_count} 条记录，最近备注为 ${data.latest_remark || "-"}，将从 ${startInput.value} 继续编号。`
        : "这是一个新的国家分组，将从 1 开始编号。";
  } catch {
    prefixInput.value = `${country}电商`;
    startInput.value = "1";
    prefixLabel.textContent = `${country}电商1`;
    metaLabel.textContent = "读取国家分组信息失败，已按默认规则填充。";
  }
}

async function refreshRelaySuggestion() {
  const relaySelect = document.querySelector("[data-relay-select]");
  const startPortInput = document.querySelector("[data-start-port-input]");
  const lineCountBadge = document.querySelector("[data-line-count]");
  const nextPortBadge = document.querySelector("[data-next-port-badge]");
  const relayRange = document.querySelector("[data-relay-preview-name]");
  const relayHost = document.querySelector("[data-relay-preview-meta]");
  const submitButton = document.querySelector("[data-loading-button]");
  const submitHint = document.querySelector("[data-submit-hint]");

  if (!relaySelect || !relayRange || !relayHost || !nextPortBadge || !submitHint) {
    return;
  }

  const selected = relaySelect.options[relaySelect.selectedIndex];
  if (!selected || !selected.value) {
    relayRange.textContent = "等待选择";
    relayHost.textContent = "这里会显示线路地址、端口段和来源。";
    nextPortBadge.textContent = "等待选择中转线路";
    if (submitButton) {
      submitButton.disabled = true;
    }
    submitHint.textContent = "请先选择一条在线线路，再继续转换。";
    return;
  }

  const active = selected.dataset.active === "true";
  const source = selected.dataset.syncSource || "local";
  relayRange.textContent = selected.dataset.name || selected.textContent.trim();
  relayHost.textContent = `${selected.dataset.host} / ${selected.dataset.rangeStart}-${selected.dataset.rangeEnd} / ${source}`;

  if (!active) {
    nextPortBadge.textContent = "当前线路离线";
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.title = "该线路当前离线，请切换";
    }
    submitHint.textContent = "该线路当前离线，请切换到其他可用线路。";
    return;
  }

  if (submitButton) {
    submitButton.disabled = false;
    submitButton.removeAttribute("title");
  }

  const lineCount = Number(lineCountBadge?.dataset.lineCountValue || "1");
  try {
    nextPortBadge.textContent = "正在检测可用端口...";
    const response = await fetch(`/api/relays/${selected.value}/next-port?count=${Math.max(lineCount, 1)}`);
    const data = await response.json();
    if (data.hasCapacity) {
      if (!startPortInput.value) {
        startPortInput.value = data.nextPort;
      }
      nextPortBadge.textContent = `建议起始端口：${data.nextPort}`;
      submitHint.textContent = `将按当前线路自动建议起始端口 ${data.nextPort}，并按输入数量连续分配。`;
    } else {
      startPortInput.value = "";
      nextPortBadge.textContent = "当前范围内没有足够的连续端口";
      submitHint.textContent = "当前线路端口已接近耗尽，请切换线路或手动调整。";
    }
  } catch {
    nextPortBadge.textContent = "端口检测失败，请稍后重试";
  }
}

function initTabs() {
  const tabTriggers = document.querySelectorAll("[data-tab-trigger]");
  tabTriggers.forEach((button, index) => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tabTrigger));
    button.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
        return;
      }
      event.preventDefault();
      const targetIndex =
        event.key === "ArrowRight"
          ? (index + 1) % tabTriggers.length
          : (index - 1 + tabTriggers.length) % tabTriggers.length;
      tabTriggers[targetIndex].focus();
      setActiveTab(tabTriggers[targetIndex].dataset.tabTrigger);
    });
  });
}

function initDashboard() {
  const rawInput = document.querySelector("[data-raw-input]");
  const lineCountBadge = document.querySelector("[data-line-count]");
  const relaySelect = document.querySelector("[data-relay-select]");
  const countryInput = document.querySelector("[data-country-input]");
  const form = document.querySelector("[data-submit-hotkey]");
  const syncToggle = document.querySelector("[data-sync-toggle]");
  const submitButton = document.querySelector("[data-loading-button]");

  initTabs();

  if (rawInput && lineCountBadge) {
    const updateLineCount = () => {
      const lineCount = countTextLines(rawInput.value);
      lineCountBadge.dataset.lineCountValue = String(lineCount || 1);
      lineCountBadge.textContent = `预计导入 ${lineCount} 行`;
      refreshRelaySuggestion();
    };
    rawInput.addEventListener("input", updateLineCount);
    updateLineCount();
  }

  if (relaySelect) {
    relaySelect.addEventListener("change", refreshRelaySuggestion);
    refreshRelaySuggestion();
  }

  if (countryInput) {
    countryInput.addEventListener("input", refreshCountryProfile);
    countryInput.addEventListener("change", refreshCountryProfile);
    refreshCountryProfile();
  }

  if (form && submitButton) {
    form.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !submitButton.disabled) {
        form.requestSubmit();
      }
    });
  }

  if (syncToggle && syncToggle.disabled && submitButton) {
    submitButton.textContent = "开始转换并保存记录";
  }
}

function initCopyButtons() {
  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      const targetId = button.getAttribute("data-copy-target");
      const target = document.getElementById(targetId);
      if (!target) {
        return;
      }

      try {
        await navigator.clipboard.writeText(target.value);
        const original = button.textContent;
        button.textContent = "已复制";
        setTimeout(() => {
          button.textContent = original;
        }, 2000);
      } catch {
        button.textContent = "失败";
      }
    });
  });
}

function initLoadingButtons() {
  document.querySelectorAll("[data-loading-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("[data-loading-button]");
      if (!button) {
        return;
      }
      button.disabled = true;
      button.textContent = "解析中...";
      window.setTimeout(() => {
        button.textContent = "同步到 Zero...";
      }, 500);
    });
  });
}

function initFlash() {
  document.querySelectorAll("[data-flash-close]").forEach((button) => {
    button.addEventListener("click", () => {
      button.closest("[data-flash-item]")?.remove();
    });
  });

  window.setTimeout(() => {
    document.querySelectorAll("[data-flash-item]").forEach((item) => item.remove());
  }, 4000);
}

document.addEventListener("DOMContentLoaded", () => {
  initDashboard();
  initCopyButtons();
  initLoadingButtons();
  initFlash();
});
