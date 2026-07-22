(function () {
  "use strict";

  var menuButton = document.getElementById("menu-button");
  var mobileMenu = document.getElementById("mobile-menu");
  var lastMenuFocus = null;

  function menuLinks() {
    return mobileMenu
      ? Array.prototype.slice.call(mobileMenu.querySelectorAll("a, button"))
      : [];
  }

  function setMenu(open, options) {
    options = options || {};
    if (!menuButton || !mobileMenu) return;

    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    mobileMenu.hidden = !open;
    document.body.classList.toggle("menu-open", open);

    if (open) {
      lastMenuFocus = document.activeElement;
      var firstLink = menuLinks()[0];
      if (firstLink) firstLink.focus();
    } else if (options.restoreFocus !== false) {
      (lastMenuFocus || menuButton).focus();
    }
  }

  if (menuButton && mobileMenu) {
    menuButton.addEventListener("click", function () {
      var open = menuButton.getAttribute("aria-expanded") !== "true";
      setMenu(open);
    });

    mobileMenu.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        setMenu(false, { restoreFocus: false });
      });
    });

    document.addEventListener("keydown", function (event) {
      if (menuButton.getAttribute("aria-expanded") !== "true") return;

      if (event.key === "Escape") {
        event.preventDefault();
        setMenu(false);
        return;
      }

      if (event.key !== "Tab") return;
      var links = menuLinks();
      if (!links.length) return;
      var first = links[0];
      var last = links[links.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 940 && menuButton.getAttribute("aria-expanded") === "true") {
        setMenu(false, { restoreFocus: false });
      }
    });
  }

  var tablist = document.querySelector('.triage__symptoms[role="tablist"]');
  var selectedIssue = "no-water";

  function activateTab(tab, moveFocus) {
    if (!tablist || !tab) return;
    var tabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'));

    tabs.forEach(function (candidate) {
      var selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      var panel = document.getElementById(candidate.getAttribute("aria-controls"));
      if (panel) panel.hidden = !selected;
    });

    selectedIssue = tab.getAttribute("data-issue") || selectedIssue;
    if (moveFocus) tab.focus();
  }

  if (tablist) {
    var symptomTabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]'));

    symptomTabs.forEach(function (tab, index) {
      tab.addEventListener("click", function () {
        activateTab(tab, false);
      });

      tab.addEventListener("keydown", function (event) {
        var nextIndex = index;

        if (event.key === "ArrowDown" || event.key === "ArrowRight") {
          nextIndex = (index + 1) % symptomTabs.length;
        } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
          nextIndex = (index - 1 + symptomTabs.length) % symptomTabs.length;
        } else if (event.key === "Home") {
          nextIndex = 0;
        } else if (event.key === "End") {
          nextIndex = symptomTabs.length - 1;
        } else {
          return;
        }

        event.preventDefault();
        activateTab(symptomTabs[nextIndex], true);
      });
    });
  }

  var requestSection = document.getElementById("request");
  var issueSelect = document.getElementById("request-issue");
  var areaInput = document.getElementById("request-area");
  var notesInput = document.getElementById("request-notes");
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function scrollToRequest(focusTarget) {
    if (!requestSection) return;
    requestSection.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    window.setTimeout(function () {
      if (focusTarget) focusTarget.focus();
    }, reducedMotion ? 0 : 360);
  }

  var useSymptomButton = document.querySelector("[data-use-symptom]");
  if (useSymptomButton && issueSelect) {
    useSymptomButton.addEventListener("click", function () {
      issueSelect.value = selectedIssue;
      clearFieldError(issueSelect);
      scrollToRequest(issueSelect);
    });
  }

  function setUrgency(value) {
    var urgency = document.querySelector('input[name="urgency"][value="' + value + '"]');
    if (urgency) urgency.checked = true;

    if (value === "emergency" && issueSelect && !issueSelect.value) {
      issueSelect.value = "no-water";
    }

    scrollToRequest(issueSelect);
  }

  document.querySelectorAll("[data-set-urgency]").forEach(function (button) {
    button.addEventListener("click", function () {
      setUrgency(button.getAttribute("data-set-urgency"));
    });
  });

  document.querySelectorAll("[data-focus-area]").forEach(function (button) {
    button.addEventListener("click", function () {
      scrollToRequest(areaInput);
    });
  });

  document.querySelectorAll("[data-plan]").forEach(function (button) {
    button.addEventListener("click", function () {
      var plan = button.getAttribute("data-plan");
      if (issueSelect) issueSelect.value = plan === "Filtration watch" ? "filtration" : "maintenance";
      if (notesInput) notesInput.value = "I would like to ask about the " + plan.toLowerCase() + " scope.";
      scrollToRequest(issueSelect);
    });
  });

  var requestForm = document.getElementById("request-form");
  var formStatus = document.getElementById("form-status");
  var formSuccess = document.getElementById("form-success");
  var submitButton = document.getElementById("request-submit");
  var submitLabel = submitButton ? submitButton.querySelector(".request-form__label") : null;
  var formReset = document.getElementById("form-reset");
  var emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  var fieldRules = {
    "request-name": {
      helpId: "request-name-help",
      errorId: "request-name-error",
      test: function (value) {
        return value.trim().length >= 2 ? "" : "Enter the name we should ask for, using at least 2 characters.";
      }
    },
    "request-phone": {
      helpId: "request-phone-help",
      errorId: "request-phone-error",
      test: function (value) {
        var digits = value.replace(/\D/g, "");
        return digits.length >= 7 ? "" : "Enter a phone number with at least 7 digits so the service details can be confirmed.";
      }
    },
    "request-email": {
      helpId: "request-email-help",
      errorId: "request-email-error",
      test: function (value) {
        return !value.trim() || emailPattern.test(value.trim())
          ? ""
          : "Enter an email in the format name@example.com, or leave this optional field blank.";
      }
    },
    "request-area": {
      helpId: "request-area-help",
      errorId: "request-area-error",
      test: function (value) {
        return value.trim().length >= 3
          ? ""
          : "Enter a road, general area or county so coverage can be checked.";
      }
    },
    "request-issue": {
      helpId: "request-issue-help",
      errorId: "request-issue-error",
      test: function (value) {
        return value ? "" : "Choose the closest water symptom so the request can be routed.";
      }
    }
  };

  function fieldRule(input) {
    return input ? fieldRules[input.id] : null;
  }

  function showFieldError(input, message) {
    var rule = fieldRule(input);
    if (!input || !rule) return;
    var error = document.getElementById(rule.errorId);
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", rule.helpId + " " + rule.errorId);
    if (error) error.textContent = message;
  }

  function clearFieldError(input) {
    var rule = fieldRule(input);
    if (!input || !rule) return;
    var error = document.getElementById(rule.errorId);
    input.removeAttribute("aria-invalid");
    input.setAttribute("aria-describedby", rule.helpId + " " + rule.errorId);
    if (error) error.textContent = "";
  }

  function validateField(input) {
    var rule = fieldRule(input);
    if (!input || !rule) return true;
    var message = rule.test(input.value);

    if (message) {
      showFieldError(input, message);
      return false;
    }

    clearFieldError(input);
    return true;
  }

  function setLoading(loading) {
    if (!submitButton) return;
    submitButton.disabled = loading;
    submitButton.classList.toggle("is-loading", loading);
    submitButton.setAttribute("aria-busy", String(loading));
    if (submitLabel) submitLabel.textContent = loading ? "Checking request" : "Check and stage request";
  }

  if (requestForm) {
    Object.keys(fieldRules).forEach(function (id) {
      var input = document.getElementById(id);
      if (!input) return;

      input.addEventListener("blur", function () {
        if (input.dataset.touched === "true" || input.value) validateField(input);
      });

      input.addEventListener("input", function () {
        input.dataset.touched = "true";
        if (input.getAttribute("aria-invalid") === "true") validateField(input);
      });

      input.addEventListener("change", function () {
        input.dataset.touched = "true";
        validateField(input);
      });
    });

    requestForm.addEventListener("submit", function (event) {
      event.preventDefault();

      var firstInvalid = null;
      var valid = true;

      Object.keys(fieldRules).forEach(function (id) {
        var input = document.getElementById(id);
        if (!validateField(input)) {
          valid = false;
          if (!firstInvalid) firstInvalid = input;
        }
      });

      if (!valid) {
        if (formStatus) formStatus.textContent = "Review the highlighted fields. Each message explains what to add or change.";
        if (firstInvalid) firstInvalid.focus();
        return;
      }

      if (formStatus) formStatus.textContent = "";
      setLoading(true);

      window.setTimeout(function () {
        setLoading(false);
        requestForm.hidden = true;
        if (formSuccess) {
          formSuccess.hidden = false;
          formSuccess.focus();
        }
      }, 850);
    });
  }

  if (formReset && requestForm && formSuccess) {
    formReset.addEventListener("click", function () {
      requestForm.reset();
      formSuccess.hidden = true;
      requestForm.hidden = false;
      if (formStatus) formStatus.textContent = "";

      Object.keys(fieldRules).forEach(function (id) {
        var input = document.getElementById(id);
        if (!input) return;
        delete input.dataset.touched;
        clearFieldError(input);
      });

      var nameInput = document.getElementById("request-name");
      if (nameInput) nameInput.focus();
    });
  }
})();
