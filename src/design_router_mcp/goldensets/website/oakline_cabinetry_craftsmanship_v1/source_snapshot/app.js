(function () {
  "use strict";

  var header = document.getElementById("siteHeader");
  var menuButton = document.getElementById("menuButton");
  var mobileMenu = document.getElementById("mobileMenu");

  function setHeaderState() {
    if (header) {
      header.classList.toggle("is-scrolled", window.scrollY > 20);
    }
  }

  function closeMenu(restoreFocus) {
    if (!menuButton || !mobileMenu) return;
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.setAttribute("aria-label", "Open menu");
    mobileMenu.hidden = true;
    document.body.classList.remove("menu-open");
    header.classList.remove("menu-active");
    if (restoreFocus) menuButton.focus();
  }

  function openMenu() {
    if (!menuButton || !mobileMenu) return;
    menuButton.setAttribute("aria-expanded", "true");
    menuButton.setAttribute("aria-label", "Close menu");
    mobileMenu.hidden = false;
    document.body.classList.add("menu-open");
    header.classList.add("menu-active");
    var firstLink = mobileMenu.querySelector("a");
    if (firstLink) firstLink.focus();
  }

  if (menuButton && mobileMenu) {
    menuButton.addEventListener("click", function () {
      if (menuButton.getAttribute("aria-expanded") === "true") {
        closeMenu(false);
      } else {
        openMenu();
      }
    });

    mobileMenu.addEventListener("click", function (event) {
      if (event.target.closest("a")) closeMenu(false);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && menuButton.getAttribute("aria-expanded") === "true") {
        closeMenu(true);
      }
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 1024) closeMenu(false);
    });
  }

  window.addEventListener("scroll", setHeaderState, { passive: true });
  setHeaderState();

  var sectionLinks = Array.prototype.slice.call(document.querySelectorAll(".desktop-nav a"));
  var sections = sectionLinks.map(function (link) {
    return document.querySelector(link.getAttribute("href"));
  }).filter(Boolean);

  if ("IntersectionObserver" in window && sections.length) {
    var sectionObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        sectionLinks.forEach(function (link) {
          if (link.getAttribute("href") === "#" + entry.target.id) {
            link.setAttribute("aria-current", "true");
          } else {
            link.removeAttribute("aria-current");
          }
        });
      });
    }, { rootMargin: "-42% 0px -52% 0px", threshold: 0 });

    sections.forEach(function (section) {
      sectionObserver.observe(section);
    });
  }

  var viewer = document.querySelector(".material-viewer");
  var readout = document.getElementById("materialReadout");
  var materialCopy = {
    wood: {
      oak: ["Rift-sawn white oak", "Straight vertical grain, warm honey tone, clear matte topcoat."],
      walnut: ["Smoked walnut", "Deep umber heartwood, softened contrast, hand-rubbed appearance."],
      sage: ["Painted sage", "Muted green-grey, satin surface, grain intentionally quiet."],
      ink: ["Painted ink", "Near-black charcoal, satin surface, crisp shadow lines."]
    },
    metal: {
      brass: "aged brass",
      black: "matte black",
      nickel: "brushed nickel"
    }
  };
  var materialState = { wood: "oak", metal: "brass" };

  function updateMaterials() {
    if (!viewer || !readout) return;
    viewer.setAttribute("data-wood", materialState.wood);
    viewer.setAttribute("data-metal", materialState.metal);
    var wood = materialCopy.wood[materialState.wood];
    var metal = materialCopy.metal[materialState.metal];
    readout.innerHTML = "<strong>" + wood[0] + "</strong> with <strong>" + metal + "</strong>. " + wood[1];
  }

  document.querySelectorAll("[data-choice-group]").forEach(function (group) {
    var key = group.getAttribute("data-choice-group");
    group.querySelectorAll(".choice").forEach(function (button) {
      button.addEventListener("click", function () {
        materialState[key] = button.getAttribute("data-value");
        group.querySelectorAll(".choice").forEach(function (peer) {
          var active = peer === button;
          peer.classList.toggle("is-active", active);
          peer.setAttribute("aria-pressed", String(active));
        });
        updateMaterials();
      });
    });
  });

  updateMaterials();

  var form = document.getElementById("consultationForm");
  var formStatus = document.getElementById("formStatus");
  var validators = {
    name: function (value) {
      return value.trim().length > 1 ? "" : "Enter your full name.";
    },
    phone: function (value) {
      return /^[\d()+\-\s.]{7,}$/.test(value.trim()) ? "" : "Enter a phone number with at least seven digits.";
    },
    email: function (value) {
      return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim()) ? "" : "Enter a valid email address.";
    },
    projectType: function (value) {
      return value ? "" : "Select a project type.";
    },
    details: function (value) {
      return value.trim().length >= 10 ? "" : "Add a little more detail about the room or project.";
    }
  };

  function validateField(field) {
    var validator = validators[field.name];
    if (!validator) return true;
    var message = validator(field.value);
    var error = document.getElementById(field.id + "Error");
    field.setAttribute("aria-invalid", message ? "true" : "false");
    if (error) error.textContent = message;
    return !message;
  }

  if (form) {
    Object.keys(validators).forEach(function (name) {
      var field = form.elements[name];
      if (!field) return;
      field.addEventListener("blur", function () {
        validateField(field);
      });
      field.addEventListener("input", function () {
        if (field.getAttribute("aria-invalid") === "true") validateField(field);
      });
    });

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var valid = true;
      Object.keys(validators).forEach(function (name) {
        if (!validateField(form.elements[name])) valid = false;
      });

      if (!valid) {
        formStatus.textContent = "Review the highlighted fields before continuing.";
        formStatus.className = "form-status";
        var firstInvalid = form.querySelector('[aria-invalid="true"]');
        if (firstInvalid) firstInvalid.focus();
        return;
      }

      formStatus.textContent = "Request ready. This visual donor preview does not send form data.";
      formStatus.className = "form-status is-success";
    });
  }
})();
