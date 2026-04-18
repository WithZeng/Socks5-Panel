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
    button.classList.toggle("active", button.dataset.tabTrigger === target);
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
  const previewCard = document.querySelector("[data-country-preview-card]");

  if (!countryInput || !prefixInput || !startInput || !prefixLabel || !metaLabel || !previewCard) {
    return;
  }

  const country = countryInput.value.trim();
  if (!country) {
    prefixInput.value = "Proxy-";
    startInput.value = "1";
    prefixLabel.textContent = "Proxy-";
    metaLabel.textContent = "选择国家后，会自动填写“国家电商”前缀并续用该分组最大编号。";
    previewCard.classList.remove("is-active");
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
        ? `当前分组已有 ${data.record_count} 条记录，最近备注为 ${data.latest_remark || "无"}，将从 ${startInput.value} 继续编号。`
        : "这是一个新的国家分组，将从 1 开始编号。";
    previewCard.classList.add("is-active");
  } catch (error) {
    prefixInput.value = `${country}电商`;
    startInput.value = "1";
    prefixLabel.textContent = `${country}电商1`;
    metaLabel.textContent = "分组画像读取失败，已按默认规则填写。";
    previewCard.classList.add("is-active");
  }
}

async function refreshRelaySuggestion() {
  const relaySelect = document.querySelector("[data-relay-select]");
  const startPortInput = document.querySelector("[data-start-port-input]");
  const lineCountBadge = document.querySelector("[data-line-count]");
  const nextPortBadge = document.querySelector("[data-next-port-badge]");
  const relayRange = document.querySelector("[data-relay-range]");
  const relayHost = document.querySelector("[data-relay-host]");
  const relayPreviewName = document.querySelector("[data-relay-preview-name]");
  const relayPreviewMeta = document.querySelector("[data-relay-preview-meta]");
  const relayPreviewCard = document.querySelector("[data-relay-preview-card]");

  if (
    !relaySelect ||
    !startPortInput ||
    !nextPortBadge ||
    !relayRange ||
    !relayHost ||
    !relayPreviewName ||
    !relayPreviewMeta ||
    !relayPreviewCard
  ) {
    return;
  }

  const selected = relaySelect.options[relaySelect.selectedIndex];
  if (!selected || !selected.value) {
    relayRange.textContent = "未选择";
    relayHost.textContent = "请选择一个可用的中转服务器。";
    relayPreviewName.textContent = "等待选择";
    relayPreviewMeta.textContent = "选择中转服务器后，这里会显示地址与可用端口段。";
    nextPortBadge.textContent = "等待选择中转服务器";
    relayPreviewCard.classList.remove("is-active");
    return;
  }

  relayRange.textContent = `${selected.dataset.rangeStart} - ${selected.dataset.rangeEnd}`;
  relayHost.textContent = `中转地址：${selected.dataset.host}`;
  relayPreviewName.textContent = selected.dataset.name || selected.textContent.trim();
  relayPreviewMeta.textContent = `${selected.dataset.host} · 端口段 ${selected.dataset.rangeStart}-${selected.dataset.rangeEnd}`;
  relayPreviewCard.classList.add("is-active");

  const lineCount = lineCountBadge ? Number(lineCountBadge.dataset.lineCount || "1") : 1;

  try {
    nextPortBadge.textContent = "正在检测可用端口...";
    const response = await fetch(`/api/relays/${selected.value}/next-port?count=${Math.max(lineCount, 1)}`);
    const data = await response.json();

    if (data.hasCapacity) {
      startPortInput.value = data.nextPort;
      nextPortBadge.textContent = `建议起始端口：${data.nextPort}`;
    } else {
      startPortInput.value = "";
      nextPortBadge.textContent = "当前范围已没有足够连续端口";
    }
  } catch (error) {
    nextPortBadge.textContent = "端口检测失败，请稍后重试";
  }
}

function initDashboard() {
  const rawInput = document.querySelector("[data-raw-input]");
  const lineCountBadge = document.querySelector("[data-line-count]");
  const relaySelect = document.querySelector("[data-relay-select]");
  const countryInput = document.querySelector("[data-country-input]");
  const tabTriggers = document.querySelectorAll("[data-tab-trigger]");

  tabTriggers.forEach((button) => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tabTrigger));
  });

  if (rawInput && lineCountBadge) {
    const updateLineCount = () => {
      const lineCount = countTextLines(rawInput.value);
      lineCountBadge.dataset.lineCount = String(lineCount || 1);
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
        }, 1500);
      } catch (error) {
        button.textContent = "复制失败";
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
      button.textContent = "处理中，请稍候...";
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initDashboard();
  initCopyButtons();
  initLoadingButtons();
});
