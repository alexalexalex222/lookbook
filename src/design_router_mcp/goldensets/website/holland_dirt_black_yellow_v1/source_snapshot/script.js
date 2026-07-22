(function () {
  "use strict";

  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  var menuButton = qs("#menuButton");
  var menuClose = qs("#menuClose");
  var mobileMenu = qs("#mobileMenu");

  function setMenu(open) {
    if (!menuButton || !mobileMenu) return;
    menuButton.setAttribute("aria-expanded", open ? "true" : "false");
    menuButton.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    mobileMenu.hidden = !open;
    document.body.classList.toggle("menu-open", open);
    if (open && menuClose) menuClose.focus();
    if (!open) menuButton.focus();
  }

  if (menuButton && mobileMenu) {
    menuButton.addEventListener("click", function () {
      setMenu(menuButton.getAttribute("aria-expanded") !== "true");
    });
    if (menuClose) {
      menuClose.addEventListener("click", function () {
        setMenu(false);
      });
    }
    qsa("a", mobileMenu).forEach(function (link) {
      link.addEventListener("click", function () {
        setMenu(false);
      });
    });
    mobileMenu.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        setMenu(false);
        return;
      }
      if (event.key !== "Tab") return;
      var focusable = qsa("a[href], button:not([disabled])", mobileMenu);
      if (!focusable.length) return;
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  var compare = qs("#compare");
  var compareBefore = qs("#compareBefore");
  var compareDivider = qs("#compareDivider");
  var compareRange = qs("#compareRange");
  var compareOutput = qs("#compareOutput");
  var compareStage = compare ? qs(".compare__stage", compare) : null;

  function setCompare(value) {
    var clamped = Math.max(5, Math.min(95, Number(value)));
    if (compare && compareStage) {
      compare.style.setProperty(
        "--compare-stage-width",
        compareStage.getBoundingClientRect().width + "px"
      );
    }
    if (compareBefore) compareBefore.style.width = clamped + "%";
    if (compareDivider) compareDivider.style.left = clamped + "%";
    if (compareRange) compareRange.value = String(clamped);
    if (compareOutput) compareOutput.textContent = (100 - clamped) + "% finished intent visible";
  }

  if (compareRange) {
    compareRange.addEventListener("input", function () {
      setCompare(compareRange.value);
    });
    setCompare(compareRange.value);
  }

  if (compare) {
    var dragging = false;

    function setFromPointer(clientX) {
      if (!compareStage) return;
      var rect = compareStage.getBoundingClientRect();
      var value = ((clientX - rect.left) / rect.width) * 100;
      setCompare(value);
    }

    compareStage.addEventListener("pointerdown", function (event) {
      dragging = true;
      compareStage.setPointerCapture(event.pointerId);
      setFromPointer(event.clientX);
    });
    compareStage.addEventListener("pointermove", function (event) {
      if (dragging) setFromPointer(event.clientX);
    });
    compareStage.addEventListener("pointerup", function (event) {
      dragging = false;
      compareStage.releasePointerCapture(event.pointerId);
    });
    compareStage.addEventListener("pointercancel", function () {
      dragging = false;
    });

    window.addEventListener("resize", function () {
      setCompare(compareRange ? compareRange.value : 48);
    });
  }

  var scopeTabs = qsa("[data-scope]");

  function selectScope(tab) {
    scopeTabs.forEach(function (item) {
      var selected = item === tab;
      var panel = qs("#scope-panel-" + item.getAttribute("data-scope"));
      item.setAttribute("aria-selected", selected ? "true" : "false");
      item.tabIndex = selected ? 0 : -1;
      if (panel) panel.hidden = !selected;
    });
  }

  scopeTabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      selectScope(tab);
    });
    tab.addEventListener("keydown", function (event) {
      var next = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        next = scopeTabs[(index + 1) % scopeTabs.length];
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        next = scopeTabs[(index - 1 + scopeTabs.length) % scopeTabs.length];
      } else if (event.key === "Home") {
        next = scopeTabs[0];
      } else if (event.key === "End") {
        next = scopeTabs[scopeTabs.length - 1];
      }
      if (next) {
        event.preventDefault();
        selectScope(next);
        next.focus();
      }
    });
  });

  var coverageForm = qs("#coverageForm");
  var coverageInput = qs("#coverageInput");
  var coverageError = qs("#coverageError");
  var coverageResult = qs("#coverageResult");

  if (coverageForm && coverageInput && coverageResult) {
    coverageForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var value = coverageInput.value.trim();
      coverageResult.hidden = true;

      if (!value) {
        coverageInput.setAttribute("aria-invalid", "true");
        coverageError.textContent = "Enter a town or county to check.";
        coverageInput.focus();
        return;
      }

      coverageInput.removeAttribute("aria-invalid");
      coverageError.textContent = "";

      coverageResult.hidden = false;
      coverageResult.setAttribute("data-state", "review");
      coverageResult.textContent =
        value +
        " is staged for a property-specific coverage review. Verify the actual service boundary, access, and travel conditions before scheduling.";
    });

    coverageInput.addEventListener("input", function () {
      if (coverageInput.getAttribute("aria-invalid") === "true") {
        coverageInput.removeAttribute("aria-invalid");
        coverageError.textContent = "";
      }
    });
  }

  var studyButtons = qsa("[data-study-filter]");
  var studies = qsa("[data-study-category]");
  var studyStatus = qs("#studyStatus");

  studyButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      var filter = button.getAttribute("data-study-filter");
      var visible = 0;

      studyButtons.forEach(function (item) {
        item.setAttribute("aria-pressed", item === button ? "true" : "false");
      });

      studies.forEach(function (study) {
        var categories = study.getAttribute("data-study-category").split(/\s+/);
        var show = filter === "all" || categories.indexOf(filter) !== -1;
        study.hidden = !show;
        if (show) visible += 1;
      });

      if (studyStatus) {
        studyStatus.textContent = visible + " structural " + (visible === 1 ? "study" : "studies") + " shown.";
      }
    });
  });

  var plannerForm = qs("#plannerForm");
  var plannerEmpty = qs("#plannerEmpty");
  var plannerDone = qs("#plannerDone");
  var plannerChecklist = qs("#plannerChecklist");
  var plannerResultTitle = qs("#plannerResultTitle");
  var plannerReset = qs("#plannerReset");

  var stageLabels = {
    "new-build": "New build site-walk brief",
    "access": "Access site-walk brief",
    "drainage": "Drainage site-walk brief",
    "cleanup": "Clearing and cleanup site-walk brief"
  };

  var stagePrompts = {
    "new-build": "Bring the current survey, site plan, or best available sketch of the intended build area.",
    "access": "Mark the intended entry, destination, and any known culvert or crossing locations.",
    "drainage": "Photograph the property during or just after rain if it is safe to do so.",
    "cleanup": "Identify what should remain, what should leave, and how debris can be handled."
  };

  var conditionPrompts = {
    timber: "Mark trees or areas that must remain before discussing the clearing limit.",
    slope: "Point out the steepest approach and where the finished surface needs to transition.",
    water: "Identify standing water, washouts, springs, ditches, and known outlets.",
    structure: "Describe the structure, slab, utilities, or debris that may affect removal."
  };

  var accessPrompts = {
    open: "Confirm gate width, overhead clearance, and where equipment can stage.",
    narrow: "Measure the narrowest point and note steep turns, soft shoulders, or low branches.",
    none: "Identify possible entry points and any neighboring or right-of-way constraints.",
    unsure: "Bring parcel access information so the working route can be evaluated on site."
  };

  function resetPlanner() {
    if (!plannerForm || !plannerEmpty || !plannerDone) return;
    plannerForm.reset();
    plannerEmpty.hidden = false;
    plannerDone.hidden = true;
    plannerForm.querySelector("select").focus();
  }

  if (plannerForm && plannerChecklist && plannerDone && plannerEmpty) {
    plannerForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var stage = qs("#plannerStage").value;
      var access = qs("#plannerAccess").value;
      var checked = qsa('input[name="condition"]:checked', plannerForm).map(function (input) {
        return input.value;
      });
      var items = [
        stagePrompts[stage],
        accessPrompts[access],
        "Have the property address, parcel information, and the best callback number ready."
      ];

      checked.forEach(function (condition) {
        items.splice(items.length - 1, 0, conditionPrompts[condition]);
      });

      plannerChecklist.innerHTML = "";
      items.forEach(function (item) {
        var li = document.createElement("li");
        li.textContent = item;
        plannerChecklist.appendChild(li);
      });

      plannerResultTitle.textContent = stageLabels[stage];
      plannerEmpty.hidden = true;
      plannerDone.hidden = false;
      plannerDone.focus();
    });
  }

  if (plannerReset) {
    plannerReset.addEventListener("click", resetPlanner);
  }

  var siteWalkForm = qs("#siteWalkForm");
  var siteWalkSuccess = qs("#siteWalkSuccess");
  var siteWalkReset = qs("#siteWalkReset");
  var siteWalkStatus = qs("#siteWalkStatus");

  var formFields = [
    {
      id: "contactName",
      error: "contactNameError",
      validate: function (value) { return value.trim().length >= 2; },
      message: "Enter the name we should use on the call."
    },
    {
      id: "contactPhone",
      error: "contactPhoneError",
      validate: function (value) { return /^[0-9()+.\-\s]{7,}$/.test(value.trim()); },
      message: "Enter a phone number with at least seven digits."
    },
    {
      id: "contactCounty",
      error: "contactCountyError",
      validate: function (value) { return value !== ""; },
      message: "Select the property area."
    },
    {
      id: "contactWork",
      error: "contactWorkError",
      validate: function (value) { return value !== ""; },
      message: "Select the primary work."
    },
    {
      id: "contactDetails",
      error: "contactDetailsError",
      validate: function (value) { return value.trim().length >= 20; },
      message: "Add at least 20 characters about access, ground conditions, or the intended work."
    }
  ];

  function validateFormField(field) {
    var input = qs("#" + field.id);
    var error = qs("#" + field.error);
    if (!input || !error) return true;
    var valid = field.validate(input.value);
    input.setAttribute("aria-invalid", valid ? "false" : "true");
    error.textContent = valid ? "" : field.message;
    return valid;
  }

  formFields.forEach(function (field) {
    var input = qs("#" + field.id);
    if (!input) return;
    input.addEventListener("blur", function () {
      validateFormField(field);
    });
    input.addEventListener("input", function () {
      if (input.getAttribute("aria-invalid") === "true") validateFormField(field);
    });
    input.addEventListener("change", function () {
      if (input.getAttribute("aria-invalid") === "true") validateFormField(field);
    });
  });

  if (siteWalkForm && siteWalkSuccess) {
    siteWalkForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var valid = true;
      var firstInvalid = null;

      formFields.forEach(function (field) {
        var fieldValid = validateFormField(field);
        if (!fieldValid && !firstInvalid) firstInvalid = qs("#" + field.id);
        valid = fieldValid && valid;
      });

      var consent = qs("#contactConsent");
      var consentError = qs("#contactConsentError");
      if (!consent.checked) {
        consent.setAttribute("aria-invalid", "true");
        consentError.textContent = "Confirm that this preview does not send the request.";
        if (!firstInvalid) firstInvalid = consent;
        valid = false;
      } else {
        consent.removeAttribute("aria-invalid");
        consentError.textContent = "";
      }

      if (!valid) {
        siteWalkStatus.textContent = "Review the highlighted fields before continuing.";
        if (firstInvalid) firstInvalid.focus();
        return;
      }

      siteWalkStatus.textContent = "";
      siteWalkForm.hidden = true;
      siteWalkSuccess.hidden = false;
      siteWalkSuccess.focus();
    });
  }

  var consentInput = qs("#contactConsent");
  if (consentInput) {
    consentInput.addEventListener("change", function () {
      if (consentInput.checked) {
        consentInput.removeAttribute("aria-invalid");
        qs("#contactConsentError").textContent = "";
      }
    });
  }

  if (siteWalkReset && siteWalkForm && siteWalkSuccess) {
    siteWalkReset.addEventListener("click", function () {
      siteWalkSuccess.hidden = true;
      siteWalkForm.hidden = false;
      qs("#contactName").focus();
    });
  }

  var currentYear = qs("#currentYear");
  if (currentYear) currentYear.textContent = String(new Date().getFullYear());
})();
