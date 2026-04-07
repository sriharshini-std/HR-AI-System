async function loadNotifications() {
    const countEl = document.getElementById("notificationCount");
    const dropdown = document.getElementById("notificationDropdown");
    if (!countEl || !dropdown) return;

    try {
        const response = await fetch("/projects/notifications/unread");
        const data = await response.json();
        countEl.textContent = data.count;

        if (!data.items.length) {
            dropdown.innerHTML = "<div class='notification-item'>No unread notifications</div>";
            return;
        }

        dropdown.innerHTML = data.items
            .map(
                (item) =>
                    `<div class='notification-item'><div>${item.message}</div><small>${item.created_at}</small></div>`
            )
            .join("");
    } catch (error) {
        dropdown.innerHTML = "<div class='notification-item'>Failed to load notifications</div>";
    }
}

async function markNotificationsRead() {
    try {
        await fetch("/projects/notifications/mark-read", { method: "POST" });
    } catch (error) {
        // Silent failure for non-critical interaction.
    }
}

function initNotifications() {
    const countBtn = document.getElementById("notificationCountBtn");
    const dropdown = document.getElementById("notificationDropdown");
    if (!countBtn || !dropdown) return;

    loadNotifications();

    countBtn.addEventListener("click", async () => {
        dropdown.classList.toggle("hidden");
        if (!dropdown.classList.contains("hidden")) {
            await loadNotifications();
            await markNotificationsRead();
            const countEl = document.getElementById("notificationCount");
            if (countEl) countEl.textContent = "0";
        }
    });

    document.addEventListener("click", (event) => {
        if (!countBtn.contains(event.target) && !dropdown.contains(event.target)) {
            dropdown.classList.add("hidden");
        }
    });
}

function initConfirmModal() {
    const modal = document.getElementById("confirmModal");
    const messageEl = document.getElementById("confirmMessage");
    const btnCancel = document.getElementById("confirmCancel");
    const btnOk = document.getElementById("confirmOk");
    if (!modal || !messageEl || !btnCancel || !btnOk) return;

    let pendingForm = null;
    let pendingLink = null;

    function closeModal() {
        pendingForm = null;
        pendingLink = null;
        modal.classList.add("hidden");
    }

    document.querySelectorAll(".confirm-form").forEach((form) => {
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            pendingForm = form;
            pendingLink = null;
            messageEl.textContent = form.dataset.confirmMessage || "Are you sure?";
            modal.classList.remove("hidden");
        });
    });

    document.querySelectorAll(".confirm-link").forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            pendingForm = null;
            pendingLink = link.getAttribute("href");
            messageEl.textContent = link.dataset.confirmMessage || "Are you sure?";
            modal.classList.remove("hidden");
        });
    });

    btnCancel.addEventListener("click", () => {
        closeModal();
    });

    btnOk.addEventListener("click", () => {
        if (pendingForm) {
            const formToSubmit = pendingForm;
            closeModal();
            formToSubmit.submit();
            return;
        }
        if (pendingLink) {
            const destination = pendingLink;
            closeModal();
            window.location.href = destination;
        }
    });

    modal.addEventListener("click", (event) => {
        if (event.target === modal) {
            closeModal();
        }
    });
}

function initDeadlineAlertsModal() {
    const trigger = document.getElementById("deadlineAlertsTrigger");
    const modal = document.getElementById("deadlineAlertsModal");
    const closeBtn = document.getElementById("deadlineAlertsClose");
    if (!trigger || !modal || !closeBtn) return;

    trigger.addEventListener("click", () => {
        modal.classList.remove("hidden");
    });

    closeBtn.addEventListener("click", () => {
        modal.classList.add("hidden");
    });

    modal.addEventListener("click", (event) => {
        if (event.target === modal) {
            modal.classList.add("hidden");
        }
    });
}

function initProjectListInteractions() {
    const rows = document.querySelectorAll(".project-row[data-url]");
    if (!rows.length) return;

    rows.forEach((row) => {
        row.addEventListener("click", (event) => {
            const target = event.target;
            if (target.closest("a, button, form, input")) return;
            const url = row.dataset.url;
            if (url) window.location.href = url;
        });
    });
}

function initMobileMenu() {
    const toggle = document.getElementById("mobileMenuToggle");
    const panel = document.getElementById("mobileMenuPanel");
    if (!toggle || !panel) return;

    toggle.addEventListener("click", () => {
        const willOpen = !panel.classList.contains("active");
        panel.classList.toggle("hidden", !willOpen);
        panel.classList.toggle("active", willOpen);
        toggle.setAttribute("aria-expanded", String(willOpen));
    });

    panel.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => {
            panel.classList.add("hidden");
            panel.classList.remove("active");
            toggle.setAttribute("aria-expanded", "false");
        });
    });

    document.addEventListener("click", (event) => {
        if (!toggle.contains(event.target) && !panel.contains(event.target)) {
            panel.classList.add("hidden");
            panel.classList.remove("active");
            toggle.setAttribute("aria-expanded", "false");
        }
    });
}

function initAdminSessionGate() {
    if (document.body.dataset.adminAuthenticated !== "1") return;

    const sessionKey = "admin_code_verified";
    if (!window.sessionStorage.getItem(sessionKey)) {
        window.location.href = "/login?reverify=1";
        return;
    }

    window.sessionStorage.setItem(sessionKey, "1");
}

function formatTimer(totalSeconds) {
    const safeSeconds = Math.max(0, Math.floor(totalSeconds));
    const hours = String(Math.floor(safeSeconds / 3600)).padStart(2, "0");
    const minutes = String(Math.floor((safeSeconds % 3600) / 60)).padStart(2, "0");
    const seconds = String(safeSeconds % 60).padStart(2, "0");
    return `${hours}:${minutes}:${seconds}`;
}

function formatLocalTime(dateObj) {
    return dateObj.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: true });
}

function initAttendanceLiveTimer() {
    const timerEl = document.getElementById("attendanceLiveTimer");
    const statusEl = document.getElementById("attendanceStatus");
    const clockInEl = document.getElementById("attendanceClockIn");
    const clockOutEl = document.getElementById("attendanceClockOut");
    const netHoursEl = document.getElementById("attendanceNetHours");
    const clockToggleLabelEl = document.getElementById("clockToggleLabel");
    const refreshmentEl = document.getElementById("refreshmentBreakValue");
    const refreshmentTimerEl = document.getElementById("refreshmentBreakTimer");
    const mealEl = document.getElementById("mealBreakValue");
    const mealTimerEl = document.getElementById("mealBreakTimer");
    const meetingEl = document.getElementById("meetingBreakValue");
    const meetingTimerEl = document.getElementById("meetingBreakTimer");
    const totalBreakEl = document.getElementById("totalBreakValue");
    const totalBreakTimerEl = document.getElementById("totalBreakTimer");
    const clockToggleBtn = document.getElementById("clockToggleBtn");
    const refreshmentBtn = document.getElementById("refreshmentBreakBtn");
    const mealBtn = document.getElementById("mealBreakBtn");
    const meetingBtn = document.getElementById("meetingBreakBtn");
    const hudGrid = document.querySelector(".attendance-hud-grid");
    const reportReminderEl = document.getElementById("reportReminderText");
    const reportReminderModal = document.getElementById("reportReminderModal");
    const reportReminderClose = document.getElementById("reportReminderClose");

    if (!timerEl || !statusEl || !clockToggleBtn) return;

    const pendingReportCount = Number(hudGrid?.dataset.pendingReports || 0);

    const state = {
        startTime: null,
        endTime: null,
        breaks: {
            refreshment: 0,
            meal: 0,
            meeting: 0,
        },
        activeBreak: null,
        breakStartedAt: null,
        intervalId: null,
    };

    function totalBreakSeconds(values = state.breaks) {
        return values.refreshment + values.meal + values.meeting;
    }

    function getDisplayedBreaks() {
        const values = {
            refreshment: state.breaks.refreshment,
            meal: state.breaks.meal,
            meeting: state.breaks.meeting,
        };

        if (state.activeBreak && state.breakStartedAt) {
            const currentBreakSeconds = Math.max(0, Math.floor((Date.now() - state.breakStartedAt.getTime()) / 1000));
            values[state.activeBreak] += currentBreakSeconds;
        }

        return values;
    }

    function updateBreakDisplay() {
        const values = getDisplayedBreaks();
        const activeBreak = state.activeBreak;
        refreshmentEl.textContent = `${Math.floor(values.refreshment / 60)} min`;
        mealEl.textContent = `${Math.floor(values.meal / 60)} min`;
        meetingEl.textContent = `${Math.floor(values.meeting / 60)} min`;
        totalBreakEl.textContent = `${Math.floor(totalBreakSeconds(values) / 60)} min`;
        if (refreshmentTimerEl) {
            refreshmentTimerEl.textContent = formatTimer(values.refreshment);
            refreshmentTimerEl.classList.toggle("active-break-timer", activeBreak === "refreshment");
        }
        if (mealTimerEl) {
            mealTimerEl.textContent = formatTimer(values.meal);
            mealTimerEl.classList.toggle("active-break-timer", activeBreak === "meal");
        }
        if (meetingTimerEl) {
            meetingTimerEl.textContent = formatTimer(values.meeting);
            meetingTimerEl.classList.toggle("active-break-timer", activeBreak === "meeting");
        }
        if (totalBreakTimerEl) {
            totalBreakTimerEl.textContent = formatTimer(totalBreakSeconds(values));
        }
    }

    function updateButtonState() {
        const isClockedIn = Boolean(state.startTime);
        const isClockedOut = Boolean(state.endTime);
        const isOnBreak = Boolean(state.activeBreak);
        clockToggleBtn.disabled = false;
        refreshmentBtn.disabled = !isClockedIn || isClockedOut || isOnBreak;
        mealBtn.disabled = !isClockedIn || isClockedOut || isOnBreak;
        meetingBtn.disabled = !isClockedIn || isClockedOut || isOnBreak;

        if (clockToggleLabelEl) {
            if (!isClockedIn) {
                clockToggleLabelEl.textContent = "Tap to clock in";
            } else if (isClockedOut) {
                clockToggleLabelEl.textContent = "Clocked out for this session";
            } else if (isOnBreak) {
                clockToggleLabelEl.textContent = "Tap to resume work";
            } else {
                clockToggleLabelEl.textContent = "Tap to clock out";
            }
        }
    }

    function renderTimer() {
        if (!state.startTime) {
            timerEl.textContent = "00:00:00";
            netHoursEl.textContent = "-";
            updateBreakDisplay();
            return;
        }

        const displayedBreaks = getDisplayedBreaks();
        const endTime = state.endTime || state.breakStartedAt || new Date();
        const committedBreakSeconds = totalBreakSeconds(state.breaks);
        const elapsedSeconds = Math.max(
            0,
            (endTime.getTime() - state.startTime.getTime()) / 1000 - committedBreakSeconds
        );

        timerEl.textContent = formatTimer(elapsedSeconds);
        netHoursEl.textContent = `${(elapsedSeconds / 3600).toFixed(2)} hrs`;
        updateBreakDisplay();
    }

    function startTicker() {
        if (state.intervalId) window.clearInterval(state.intervalId);
        state.intervalId = window.setInterval(renderTimer, 1000);
    }

    function stopTicker() {
        if (!state.intervalId) return;
        window.clearInterval(state.intervalId);
        state.intervalId = null;
    }

    function showReportReminderModal() {
        if (!reportReminderModal) return;
        reportReminderModal.classList.remove("hidden");
    }

    function hideReportReminderModal() {
        if (!reportReminderModal) return;
        reportReminderModal.classList.add("hidden");
    }

    if (reportReminderClose) {
        reportReminderClose.addEventListener("click", hideReportReminderModal);
    }

    if (reportReminderModal) {
        reportReminderModal.addEventListener("click", (event) => {
            if (event.target === reportReminderModal) {
                hideReportReminderModal();
            }
        });
    }

    clockToggleBtn.addEventListener("click", () => {
        if (!state.startTime) {
            state.startTime = new Date();
            state.endTime = null;
            state.breaks.refreshment = 0;
            state.breaks.meal = 0;
            state.breaks.meeting = 0;
            state.activeBreak = null;
            state.breakStartedAt = null;
            statusEl.textContent = "Clocked in";
            clockInEl.textContent = formatLocalTime(state.startTime);
            clockOutEl.textContent = "-";
            updateBreakDisplay();
            renderTimer();
            updateButtonState();
            startTicker();
            return;
        }

        if (state.activeBreak && state.breakStartedAt) {
            const breakSeconds = Math.max(0, Math.floor((Date.now() - state.breakStartedAt.getTime()) / 1000));
            state.breaks[state.activeBreak] += breakSeconds;
            state.activeBreak = null;
            state.breakStartedAt = null;
            statusEl.textContent = "Clocked in";
            updateButtonState();
            renderTimer();
            return;
        }

        if (!state.endTime && !state.activeBreak) {
            if (pendingReportCount > 0) {
                statusEl.textContent = "Report pending";
                if (reportReminderEl) {
                    reportReminderEl.textContent = "Submit today's project reports before clocking out.";
                }
                showReportReminderModal();
                return;
            }
            state.endTime = new Date();
            statusEl.textContent = "Clocked out";
            clockOutEl.textContent = formatLocalTime(state.endTime);
            renderTimer();
            updateButtonState();
            stopTicker();
        }
    });

    refreshmentBtn.addEventListener("click", () => {
        if (!state.startTime || state.endTime || state.activeBreak) return;
        state.activeBreak = "refreshment";
        state.breakStartedAt = new Date();
        statusEl.textContent = "On refreshment break";
        updateButtonState();
        renderTimer();
    });

    mealBtn.addEventListener("click", () => {
        if (!state.startTime || state.endTime || state.activeBreak) return;
        state.activeBreak = "meal";
        state.breakStartedAt = new Date();
        statusEl.textContent = "On meal break";
        updateButtonState();
        renderTimer();
    });

    meetingBtn.addEventListener("click", () => {
        if (!state.startTime || state.endTime || state.activeBreak) return;
        state.activeBreak = "meeting";
        state.breakStartedAt = new Date();
        statusEl.textContent = "In meeting";
        updateButtonState();
        renderTimer();
    });

    updateBreakDisplay();
    updateButtonState();
    renderTimer();
}

function initSkillSearchPicker() {
    const picker = document.getElementById("skillSearchPicker");
    const input = document.getElementById("skillSearchInput");
    const filterButtons = Array.from(document.querySelectorAll(".skill-filter-btn"));
    const datalist = document.getElementById("skillSearchOptions");
    const scopeInput = document.getElementById("skillScopeInput");
    const tagsWrap = document.getElementById("selectedSkillTags");
    const hiddenInputsWrap = document.getElementById("selectedSkillInputs");
    if (!picker || !input || !datalist || !scopeInput || !tagsWrap || !hiddenInputsWrap) return;

    const initialSkills = JSON.parse(picker.dataset.initialSkills || "[]");
    const requiredSkills = JSON.parse(picker.dataset.requiredSkills || "[]");
    const allSkills = JSON.parse(picker.dataset.allSkills || "[]");
    let activeScope = picker.dataset.selectedScope || (requiredSkills.length ? "required" : "all");
    const selectedSkills = new Map();

    function currentScopeSkills() {
        return activeScope === "required" && requiredSkills.length ? requiredSkills : allSkills;
    }

    function normalizeSkill(value) {
        const trimmed = (value || "").trim();
        if (!trimmed) return "";
        const availableValues = currentScopeSkills();
        const match = availableValues.find((item) => item.toLowerCase() === trimmed.toLowerCase());
        if (match) return match;
        const fallback = allSkills.find((item) => item.toLowerCase() === trimmed.toLowerCase());
        return fallback || trimmed;
    }

    function renderAvailableSkills() {
        const skills = currentScopeSkills();
        scopeInput.value = activeScope;

        filterButtons.forEach((button) => {
            button.classList.toggle("active", button.dataset.scope === activeScope);
        });

        datalist.innerHTML = "";
        skills.forEach((skillName) => {
            const option = document.createElement("option");
            option.value = skillName;
            datalist.appendChild(option);
        });
    }

    function renderSkills() {
        tagsWrap.innerHTML = "";
        hiddenInputsWrap.innerHTML = "";

        selectedSkills.forEach((skillName) => {
            const tag = document.createElement("span");
            tag.className = "skill-pill";
            tag.innerHTML = `${skillName} <button type="button" class="skill-pill-remove" aria-label="Remove ${skillName}">&times;</button>`;
            tag.querySelector("button").addEventListener("click", () => {
                selectedSkills.delete(skillName.toLowerCase());
                renderSkills();
            });
            tagsWrap.appendChild(tag);

            const hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.name = "selected_skills";
            hiddenInput.value = skillName;
            hiddenInputsWrap.appendChild(hiddenInput);
        });
    }

    function addSkill(value) {
        const normalized = normalizeSkill(value);
        if (!normalized) return;
        selectedSkills.set(normalized.toLowerCase(), normalized);
        input.value = "";
        renderSkills();
    }

    renderAvailableSkills();
    initialSkills.forEach((skillName) => addSkill(skillName));

    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            addSkill(input.value);
        }
    });
    filterButtons.forEach((button) => {
        button.addEventListener("click", () => {
            activeScope = button.dataset.scope || activeScope;
            renderAvailableSkills();
        });
    });
}

function initLiveSearchForms() {
    const forms = document.querySelectorAll(".live-search-form[data-live-search]");
    if (!forms.length) return;

    forms.forEach((form) => {
        const input = form.querySelector(".live-search-input");
        const dropdown = form.querySelector(".live-search-dropdown");
        if (!input || !dropdown) return;

        let searchItems = [];
        try {
            searchItems = JSON.parse(form.dataset.liveSearch || "[]");
        } catch (error) {
            searchItems = [];
        }

        function scoreItem(item, query) {
            const value = String(item.value || "").toLowerCase();
            const meta = String(item.meta || "").toLowerCase();
            const category = String(item.category || "").toLowerCase();
            let score = 0;

            if (value.startsWith(query)) score += 6;
            else if (value.includes(query)) score += 4;

            if (meta.startsWith(query)) score += 3;
            else if (meta.includes(query)) score += 2;

            if (category.includes(query)) score += 1;
            return score;
        }

        function hideDropdown() {
            dropdown.innerHTML = "";
            dropdown.classList.add("hidden");
        }

        function renderResults() {
            const query = input.value.trim().toLowerCase();
            if (!query) {
                hideDropdown();
                return [];
            }

            const matches = searchItems
                .map((item) => ({ ...item, _score: scoreItem(item, query) }))
                .filter((item) => item._score > 0)
                .sort((a, b) => {
                    if (b._score !== a._score) return b._score - a._score;
                    return String(a.value || "").localeCompare(String(b.value || ""));
                })
                .slice(0, 10);

            if (!matches.length) {
                hideDropdown();
                return [];
            }

            const groups = new Map();
            matches.forEach((item) => {
                const key = item.category || "Results";
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(item);
            });

            dropdown.innerHTML = "";
            groups.forEach((items, category) => {
                const group = document.createElement("div");
                group.className = "live-search-group";

                const title = document.createElement("div");
                title.className = "live-search-group-title";
                title.textContent = category;
                group.appendChild(title);

                items.forEach((item) => {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "live-search-item";
                    button.innerHTML = `<strong>${item.value || ""}</strong><small>${item.meta || ""}</small>`;
                    button.addEventListener("click", () => {
                        input.value = item.value || "";
                        hideDropdown();
                        if (item.url) {
                            window.location.href = item.url;
                            return;
                        }
                    });
                    group.appendChild(button);
                });

                dropdown.appendChild(group);
            });

            dropdown.classList.remove("hidden");
            return matches;
        }

        input.addEventListener("input", () => {
            renderResults();
        });

        input.addEventListener("focus", () => {
            if (input.value.trim()) {
                renderResults();
            }
        });

        form.addEventListener("submit", (event) => {
            if (form.dataset.liveSearchNoSubmit !== "1") return;
            event.preventDefault();
            const matches = renderResults();
            if (matches.length && matches[0].url) {
                window.location.href = matches[0].url;
            }
        });

        document.addEventListener("click", (event) => {
            if (!form.contains(event.target)) {
                hideDropdown();
            }
        });
    });
}

function initPasswordToggles() {
    document.querySelectorAll("[data-toggle-password]").forEach((button) => {
        button.addEventListener("click", () => {
            const fieldWrap = button.closest(".password-field");
            const input = fieldWrap?.querySelector("input");
            const icon = button.querySelector("i");
            if (!input || !icon) return;

            const willShow = input.type === "password";
            input.type = willShow ? "text" : "password";
            button.setAttribute("aria-label", willShow ? "Hide password" : "Show password");
            icon.className = willShow ? "fa-regular fa-eye-slash" : "fa-regular fa-eye";
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    initAdminSessionGate();
    initNotifications();
    initConfirmModal();
    initDeadlineAlertsModal();
    initProjectListInteractions();
    initMobileMenu();
    initAttendanceLiveTimer();
    initSkillSearchPicker();
    initLiveSearchForms();
    initPasswordToggles();
});
