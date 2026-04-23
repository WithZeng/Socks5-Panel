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

function initSidebar() {
  const openButton = document.querySelector("[data-sidebar-open]");
  const closeButton = document.querySelector("[data-sidebar-close]");
  const backdrop = document.querySelector("[data-sidebar-backdrop]");

  const open = () => document.body.classList.add("sidebar-open");
  const close = () => document.body.classList.remove("sidebar-open");

  openButton?.addEventListener("click", open);
  closeButton?.addEventListener("click", close);
  backdrop?.addEventListener("click", close);
}

function initDismissibleBanners() {
  document.querySelectorAll("[data-dismissible-banner]").forEach((banner) => {
    const key = banner.getAttribute("data-dismissible-banner");
    const hidden = sessionStorage.getItem(`dismiss:${key}`);
    if (hidden === "true") {
      banner.remove();
      return;
    }

    banner.querySelector("[data-banner-close]")?.addEventListener("click", () => {
      sessionStorage.setItem(`dismiss:${key}`, "true");
      banner.remove();
    });
  });
}

function initSettingsTabs() {
  const tabs = document.querySelectorAll("[data-settings-tab]");
  const panels = document.querySelectorAll("[data-settings-panel]");
  if (!tabs.length || !panels.length) {
    return;
  }

  const activate = (hash) => {
    const targetHash = hash || "#connection";
    tabs.forEach((tab) => {
      tab.classList.toggle("is-active", tab.getAttribute("href") === targetHash);
    });
    panels.forEach((panel) => {
      panel.classList.toggle("is-active", `#${panel.id}` === targetHash);
    });
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", (event) => {
      event.preventDefault();
      const hash = tab.getAttribute("href");
      history.replaceState(null, "", hash);
      activate(hash);
    });
  });

  activate(window.location.hash);
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

function applyPresetConfig(config, selectedLabel) {
  const setCheckbox = (selector, value) => {
    const field = document.querySelector(selector);
    if (field) {
      field.checked = Boolean(value);
    }
  };

  const setValue = (selector, value) => {
    const field = document.querySelector(selector);
    if (field) {
      field.value = value ?? "";
    }
  };

  setCheckbox("[data-zero-chain-mode]", config.chain_mode);
  setCheckbox("[data-zero-smart-select]", config.forward_chain_smart_select);
  setCheckbox("[data-zero-enable-udp]", config.enable_udp);
  setValue("[data-zero-fixed-hops]", config.forward_chain_fixed_hops_num ?? 0);
  setValue("[data-zero-fixed-last-hops]", config.forward_chain_fixed_last_hops_num ?? 0);
  setValue("[data-zero-balance-strategy]", config.balance_strategy ?? 0);
  setValue("[data-zero-target-select-mode]", config.target_select_mode ?? 0);
  setValue("[data-zero-test-method]", config.test_method ?? 1);
  setValue("[data-zero-accept-proxy]", config.accept_proxy_protocol ? "1" : "0");
  setValue("[data-zero-send-proxy]", config.send_proxy_protocol_version ?? "");
  setValue("[data-zero-tags]", (config.tags || []).join(","));
  setValue("[data-zero-custom-config]", config.custom_config ? JSON.stringify(config.custom_config, null, 2) : "");

  const forwardSelect = document.querySelector("[data-zero-forward-endpoints]");
  if (forwardSelect) {
    const values = new Set((config.forward_endpoints || []).map(String));
    Array.from(forwardSelect.options).forEach((option) => {
      option.selected = values.has(option.value);
    });
  }

  const presetName = document.querySelector("[data-preset-name]");
  const presetDescription = document.querySelector("[data-preset-description]");
  if (presetName) {
    presetName.textContent = selectedLabel || "已套用预设";
  }
  if (presetDescription) {
    presetDescription.textContent = "预设已套用。你仍然可以继续修改字段后再提交。";
  }
}

function initDashboard() {
  const rawInput = document.querySelector("[data-raw-input]");
  const lineCountBadge = document.querySelector("[data-line-count]");
  const relaySelect = document.querySelector("[data-relay-select]");
  const countryInput = document.querySelector("[data-country-input]");
  const form = document.querySelector("[data-submit-hotkey]");
  const syncToggle = document.querySelector("[data-sync-toggle]");
  const submitButton = document.querySelector("[data-loading-button]");
  const presetSelect = document.querySelector("[data-zero-preset-select]");

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

  if (presetSelect) {
    const handlePresetChange = () => {
      const selected = presetSelect.options[presetSelect.selectedIndex];
      if (!selected || !selected.value) {
        return;
      }
      try {
        const config = JSON.parse(selected.dataset.config || "{}");
        applyPresetConfig(config, selected.textContent.trim());
      } catch {
        const presetDescription = document.querySelector("[data-preset-description]");
        if (presetDescription) {
          presetDescription.textContent = "预设解析失败，请检查预设配置。";
        }
      }
    };

    presetSelect.addEventListener("change", handlePresetChange);
    if (presetSelect.value) {
      handlePresetChange();
    }
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
  initSidebar();
  initDismissibleBanners();
  initSettingsTabs();
  initDashboard();
  initCopyButtons();
  initLoadingButtons();
  initFlash();
});
