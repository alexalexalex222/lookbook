(function () {
  "use strict";

  document.documentElement.classList.remove("no-js");

  var prefersReducedMotion = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;

  var header = document.querySelector("[data-header]");
  if (header) {
    var updateHeader = function () {
      header.classList.toggle("is-elevated", window.scrollY > 10);
    };

    updateHeader();
    window.addEventListener("scroll", updateHeader, { passive: true });
  }

  var menuButton = document.querySelector("[data-menu-button]");
  var mobileMenu = document.querySelector("[data-mobile-menu]");

  if (menuButton && mobileMenu) {
    var setMenuOpen = function (open, returnFocus) {
      menuButton.setAttribute("aria-expanded", String(open));
      menuButton.setAttribute("aria-label", open ? "Close menu" : "Open menu");
      mobileMenu.hidden = !open;
      document.body.classList.toggle("menu-open", open);

      if (open) {
        var firstLink = mobileMenu.querySelector("a");
        if (firstLink) firstLink.focus();
      } else if (returnFocus) {
        menuButton.focus();
      }
    };

    menuButton.addEventListener("click", function () {
      setMenuOpen(menuButton.getAttribute("aria-expanded") !== "true", false);
    });

    mobileMenu.addEventListener("click", function (event) {
      if (event.target.closest("a")) setMenuOpen(false, false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && menuButton.getAttribute("aria-expanded") === "true") {
        setMenuOpen(false, true);
      }
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 980 && menuButton.getAttribute("aria-expanded") === "true") {
        setMenuOpen(false, false);
      }
    });
  }

  var initializeTabs = function (root, tabSelector, activate) {
    if (!root) return;

    var tabs = Array.prototype.slice.call(root.querySelectorAll(tabSelector));
    if (!tabs.length) return;

    root.addEventListener("click", function (event) {
      var tab = event.target.closest(tabSelector);
      if (tab && tabs.indexOf(tab) !== -1) activate(tab, tabs, false);
    });

    root.addEventListener("keydown", function (event) {
      var currentIndex = tabs.indexOf(document.activeElement);
      if (currentIndex < 0) return;

      var nextIndex = currentIndex;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        nextIndex = (currentIndex + 1) % tabs.length;
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
      } else if (event.key === "Home") {
        nextIndex = 0;
      } else if (event.key === "End") {
        nextIndex = tabs.length - 1;
      } else {
        return;
      }

      event.preventDefault();
      activate(tabs[nextIndex], tabs, true);
    });
  };

  var programRoot = document.querySelector("[data-program-tabs]");
  initializeTabs(programRoot, '[role="tab"]', function (activeTab, tabs, moveFocus) {
    tabs.forEach(function (tab) {
      var selected = tab === activeTab;
      var panel = document.getElementById(tab.getAttribute("aria-controls"));

      tab.setAttribute("aria-selected", String(selected));
      tab.setAttribute("tabindex", selected ? "0" : "-1");

      if (panel) {
        panel.hidden = !selected;
        panel.classList.toggle("is-active", selected);
      }
    });

    if (moveFocus) activeTab.focus();
  });

  var dayTabs = document.querySelector("[data-day-tabs]");
  var scheduleGrid = document.querySelector("[data-schedule-grid]");

  initializeTabs(dayTabs, "[data-day-button]", function (activeTab, tabs, moveFocus) {
    var activeDay = activeTab.getAttribute("data-day-button");

    tabs.forEach(function (tab) {
      var selected = tab === activeTab;
      tab.setAttribute("aria-selected", String(selected));
      tab.setAttribute("tabindex", selected ? "0" : "-1");
    });

    if (scheduleGrid) {
      scheduleGrid.querySelectorAll("[data-schedule-day]").forEach(function (day) {
        day.classList.toggle(
          "is-selected",
          day.getAttribute("data-schedule-day") === activeDay
        );
      });
    }

    if (moveFocus) activeTab.focus();
  });

  document.querySelectorAll(".faq-list details").forEach(function (details) {
    details.addEventListener("toggle", function () {
      if (!details.open) return;

      document.querySelectorAll(".faq-list details").forEach(function (other) {
        if (other !== details) other.open = false;
      });
    });
  });

  var form = document.getElementById("trial-form");
  var successPanel = document.getElementById("form-success");
  var resetButton = document.getElementById("form-reset");

  if (form && successPanel) {
    var summary = document.getElementById("form-summary");
    var submitButton = document.getElementById("trial-submit");
    var submitLabel = submitButton
      ? submitButton.querySelector(".button__label")
      : null;

    var fields = [
      {
        id: "trial-name",
        helpId: "trial-name-help",
        errorId: "trial-name-error",
        validate: function (field) {
          return field.value.trim().length >= 2
            ? ""
            : "Enter at least two characters for the name the academy should use.";
        }
      },
      {
        id: "trial-email",
        helpId: "trial-email-help",
        errorId: "trial-email-error",
        validate: function (field) {
          var value = field.value.trim();
          if (!value) return "Enter an email address so the trial can be confirmed.";
          return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)
            ? ""
            : "Use a complete email address, such as name@example.com.";
        }
      },
      {
        id: "trial-program",
        helpId: "trial-program-help",
        errorId: "trial-program-error",
        validate: function (field) {
          return field.value
            ? ""
            : "Choose a starting track, or select Not sure yet.";
        }
      },
      {
        id: "trial-consent",
        helpId: "trial-consent-help",
        errorId: "trial-consent-error",
        validate: function (field) {
          return field.checked
            ? ""
            : "Confirm that the academy may contact you about this request.";
        }
      }
    ];

    var setFieldError = function (config, message) {
      var field = document.getElementById(config.id);
      var error = document.getElementById(config.errorId);
      if (!field || !error) return;

      if (message) {
        field.setAttribute("aria-invalid", "true");
        field.setAttribute(
          "aria-describedby",
          config.helpId + " " + config.errorId
        );
        error.textContent = message;
        error.hidden = false;
      } else {
        field.removeAttribute("aria-invalid");
        field.setAttribute("aria-describedby", config.helpId);
        error.textContent = "";
        error.hidden = true;
      }
    };

    var validateField = function (config) {
      var field = document.getElementById(config.id);
      if (!field) return true;

      var message = config.validate(field);
      setFieldError(config, message);
      return !message;
    };

    fields.forEach(function (config) {
      var field = document.getElementById(config.id);
      if (!field) return;

      var eventName =
        field.type === "checkbox" || field.tagName === "SELECT"
          ? "change"
          : "blur";

      field.addEventListener(eventName, function () {
        field.dataset.touched = "true";
        validateField(config);
      });

      field.addEventListener("input", function () {
        if (field.getAttribute("aria-invalid") === "true") {
          validateField(config);
        }
      });
    });

    var setSubmitting = function (submitting) {
      if (!submitButton) return;

      submitButton.disabled = submitting;
      submitButton.setAttribute("aria-busy", String(submitting));
      if (submitLabel) {
        submitLabel.textContent = submitting
          ? "Checking request"
          : "Prepare trial request";
      }
    };

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var firstInvalid = null;
      var allValid = true;

      fields.forEach(function (config) {
        var valid = validateField(config);
        if (!valid) {
          allValid = false;
          if (!firstInvalid) firstInvalid = document.getElementById(config.id);
        }
      });

      if (!allValid) {
        if (summary) {
          summary.textContent =
            "Review the highlighted fields. Each message explains what to change.";
        }
        if (firstInvalid) firstInvalid.focus();
        return;
      }

      if (summary) summary.textContent = "";
      setSubmitting(true);

      window.setTimeout(function () {
        setSubmitting(false);
        form.hidden = true;
        successPanel.hidden = false;
        successPanel.focus();
      }, prefersReducedMotion ? 0 : 500);
    });

    if (resetButton) {
      resetButton.addEventListener("click", function () {
        form.reset();
        fields.forEach(function (config) {
          var field = document.getElementById(config.id);
          if (field) delete field.dataset.touched;
          setFieldError(config, "");
        });
        if (summary) summary.textContent = "";
        successPanel.hidden = true;
        form.hidden = false;

        var firstField = document.getElementById("trial-name");
        if (firstField) firstField.focus();
      });
    }
  }
})();
