(function () {
  "use strict";

  var queueBody = document.getElementById("queueBody");
  var queueSearch = document.getElementById("queueSearch");
  var filterButtons = Array.prototype.slice.call(document.querySelectorAll("[data-filter]"));
  var queueFeedback = document.getElementById("queueFeedback");
  var activeFilter = "all";

  function queueRows() {
    return queueBody ? Array.prototype.slice.call(queueBody.querySelectorAll(".queue-row")) : [];
  }

  function applyQueueView() {
    var query = queueSearch ? queueSearch.value.trim().toLowerCase() : "";
    var visible = 0;

    queueRows().forEach(function (row) {
      var filterMatches = activeFilter === "all" || row.dataset.status === activeFilter;
      var searchMatches = !query || row.textContent.toLowerCase().indexOf(query) !== -1;
      row.hidden = !(filterMatches && searchMatches);
      if (!row.hidden) visible += 1;
    });

    if (queueFeedback) {
      queueFeedback.textContent = visible
        ? "Showing " + visible + " sample signal" + (visible === 1 ? "." : "s.")
        : "No sample signals match this view.";
    }
  }

  filterButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      activeFilter = button.dataset.filter;
      filterButtons.forEach(function (candidate) {
        var selected = candidate === button;
        candidate.classList.toggle("is-active", selected);
        candidate.setAttribute("aria-pressed", String(selected));
      });
      applyQueueView();
    });
  });

  if (queueSearch) {
    queueSearch.addEventListener("input", applyQueueView);
  }

  function selectRow(row) {
    queueRows().forEach(function (candidate) {
      var selected = candidate === row;
      candidate.classList.toggle("is-selected", selected);
      var signalButton = candidate.querySelector(".signal-cell");
      if (signalButton) signalButton.setAttribute("aria-pressed", String(selected));
    });

    var statusClass = row.dataset.status === "risk"
      ? "status-risk"
      : row.dataset.status === "review"
        ? "status-review"
        : "status-track";
    var detailStatus = document.getElementById("detailStatus");

    document.getElementById("detailTitle").textContent = row.dataset.signal;
    document.getElementById("detailSummary").textContent = row.dataset.summary;
    document.getElementById("detailSource").textContent = row.dataset.source;
    document.getElementById("detailOwner").textContent = row.dataset.owner;
    detailStatus.textContent = row.dataset.state;
    detailStatus.className = "status " + statusClass;
    document.getElementById("detailFeedback").textContent = "";
  }

  if (queueBody) {
    queueBody.addEventListener("click", function (event) {
      var row = event.target.closest(".queue-row");
      if (!row) return;

      if (event.target.closest(".signal-cell")) {
        selectRow(row);
        return;
      }

      var action = event.target.closest("[data-action]");
      if (action) {
        var label = action.dataset.action;
        action.textContent = label === "claim" ? "Claimed" : label === "snooze" ? "Snoozed" : label === "reassign" ? "Queued" : "Opened";
        action.disabled = true;
        if (queueFeedback) queueFeedback.textContent = "Sample action updated locally.";
      }
    });
  }

  Array.prototype.slice.call(document.querySelectorAll("[data-detail-action]")).forEach(function (button) {
    button.addEventListener("click", function () {
      var feedback = document.getElementById("detailFeedback");
      var action = button.dataset.detailAction === "claim" ? "claimed" : "snoozed";
      feedback.textContent = "Selected sample signal " + action + ".";
    });
  });

  var roleTabs = Array.prototype.slice.call(document.querySelectorAll(".role-tabs [role='tab']"));

  function activateRoleTab(tab, focusTab) {
    roleTabs.forEach(function (candidate) {
      var selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      var panel = document.getElementById(candidate.getAttribute("aria-controls"));
      if (panel) panel.hidden = !selected;
    });
    if (focusTab) tab.focus();
  }

  roleTabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      activateRoleTab(tab, false);
    });
    tab.addEventListener("keydown", function (event) {
      var nextIndex = index;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % roleTabs.length;
      else if (event.key === "ArrowLeft") nextIndex = (index - 1 + roleTabs.length) % roleTabs.length;
      else if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = roleTabs.length - 1;
      else return;
      event.preventDefault();
      activateRoleTab(roleTabs[nextIndex], true);
    });
  });

  Array.prototype.slice.call(document.querySelectorAll(".mobile-menu-panel a")).forEach(function (link) {
    link.addEventListener("click", function () {
      var menu = link.closest("details");
      if (menu) menu.open = false;
    });
  });

  Array.prototype.slice.call(document.querySelectorAll("[data-state-action]")).forEach(function (button) {
    button.addEventListener("click", function () {
      var feedback = button.parentElement.querySelector(".state-feedback");
      if (button.dataset.stateAction === "clear") {
        activeFilter = "all";
        if (queueSearch) queueSearch.value = "";
        filterButtons.forEach(function (candidate) {
          var selected = candidate.dataset.filter === "all";
          candidate.classList.toggle("is-active", selected);
          candidate.setAttribute("aria-pressed", String(selected));
        });
        applyQueueView();
        if (feedback) feedback.textContent = "Sample queue filters cleared.";
      } else if (button.dataset.stateAction === "retry") {
        button.textContent = "Connected";
        button.disabled = true;
        if (feedback) feedback.textContent = "Sample connector restored.";
      }
    });
  });

  var demoForm = document.getElementById("demoForm");
  if (demoForm) {
    demoForm.noValidate = true;
    var demoFields = {
      email: {
        input: document.getElementById("email"),
        error: document.getElementById("emailError"),
        validate: function (value) {
          if (!value.trim()) return "Enter a work email.";
          return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim()) ? "" : "Enter a valid email address.";
        }
      },
      source: {
        input: document.getElementById("source"),
        error: document.getElementById("sourceError"),
        validate: function (value) {
          return value ? "" : "Select the primary event source.";
        }
      },
      workflow: {
        input: document.getElementById("workflow-input"),
        error: document.getElementById("workflowError"),
        validate: function (value) {
          return value.trim().length >= 3 ? "" : "Describe the workflow in at least three characters.";
        }
      }
    };

    function validateDemoField(name) {
      var field = demoFields[name];
      var message = field.validate(field.input.value);
      field.input.setAttribute("aria-invalid", String(Boolean(message)));
      field.error.textContent = message;
      return !message;
    }

    Object.keys(demoFields).forEach(function (name) {
      var field = demoFields[name];
      field.input.addEventListener("blur", function () {
        validateDemoField(name);
      });
      field.input.addEventListener("input", function () {
        if (field.input.getAttribute("aria-invalid") === "true") validateDemoField(name);
      });
      field.input.addEventListener("change", function () {
        if (field.input.getAttribute("aria-invalid") === "true") validateDemoField(name);
      });
    });

    demoForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var names = Object.keys(demoFields);
      var results = names.map(validateDemoField);
      if (results.indexOf(false) !== -1) {
        demoFields[names[results.indexOf(false)]].input.focus();
        document.getElementById("formStatus").textContent = "Fix the highlighted fields before requesting a walkthrough.";
        return;
      }
      document.getElementById("formStatus").textContent = "Request prepared in this static concept. No data was sent.";
    });
  }
})();
