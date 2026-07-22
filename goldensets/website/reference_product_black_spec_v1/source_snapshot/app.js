(function () {
  "use strict";

  var header = document.getElementById("siteHeader");
  var menuButton = document.getElementById("menuButton");
  var mobileMenu = document.getElementById("mobileMenu");
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function setHeaderState() {
    if (header) header.classList.toggle("is-scrolled", window.scrollY > 20);
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
      if (menuButton.getAttribute("aria-expanded") === "true") closeMenu(false);
      else openMenu();
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

  var navLinks = Array.prototype.slice.call(document.querySelectorAll(".desktop-nav a"));
  var navSections = navLinks.map(function (link) {
    return document.querySelector(link.getAttribute("href"));
  }).filter(Boolean);

  if ("IntersectionObserver" in window && navSections.length) {
    var navObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        navLinks.forEach(function (link) {
          if (link.getAttribute("href") === "#" + entry.target.id) link.setAttribute("aria-current", "true");
          else link.removeAttribute("aria-current");
        });
      });
    }, { rootMargin: "-43% 0px -51% 0px", threshold: 0 });

    navSections.forEach(function (section) {
      navObserver.observe(section);
    });
  }

  var heroWatch = document.getElementById("heroWatch");
  if (heroWatch && !reduceMotion && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    heroWatch.addEventListener("pointermove", function (event) {
      var rect = heroWatch.getBoundingClientRect();
      var x = (event.clientX - rect.left) / rect.width - 0.5;
      var y = (event.clientY - rect.top) / rect.height - 0.5;
      heroWatch.style.setProperty("--watch-x", (x * 7).toFixed(2) + "deg");
      heroWatch.style.setProperty("--watch-y", (y * -5).toFixed(2) + "deg");
    });
    heroWatch.addEventListener("pointerleave", function () {
      heroWatch.style.setProperty("--watch-x", "0deg");
      heroWatch.style.setProperty("--watch-y", "0deg");
    });
  }

  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"][data-detail]'));
  var panels = Array.prototype.slice.call(document.querySelectorAll(".detail-panel[data-panel]"));

  function selectDetail(tab, moveFocus) {
    var detail = tab.getAttribute("data-detail");
    tabs.forEach(function (peer) {
      var selected = peer === tab;
      peer.setAttribute("aria-selected", String(selected));
      peer.tabIndex = selected ? 0 : -1;
    });
    panels.forEach(function (panel) {
      var selected = panel.getAttribute("data-panel") === detail;
      panel.classList.toggle("is-active", selected);
      panel.hidden = !selected;
    });
    if (moveFocus) tab.focus();
  }

  tabs.forEach(function (tab, index) {
    tab.addEventListener("click", function () {
      selectDetail(tab, false);
    });

    tab.addEventListener("keydown", function (event) {
      var nextIndex = index;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === "Home") nextIndex = 0;
      else if (event.key === "End") nextIndex = tabs.length - 1;
      else return;
      event.preventDefault();
      selectDetail(tabs[nextIndex], true);
    });

  });

  if (tabs.length) selectDetail(tabs[0], false);

  var stickyReserve = document.getElementById("stickyReserve");
  var hero = document.getElementById("top");
  var reserve = document.getElementById("reserve");
  var footer = document.querySelector(".site-footer");

  if (stickyReserve && hero && reserve && footer && "IntersectionObserver" in window) {
    var heroVisible = true;
    var reserveVisible = false;
    var footerVisible = false;

    function syncSticky() {
      var visible = !heroVisible && !reserveVisible && !footerVisible;
      stickyReserve.classList.toggle("is-visible", visible);
      stickyReserve.setAttribute("aria-hidden", String(!visible));
    }

    new IntersectionObserver(function (entries) {
      heroVisible = entries[0].isIntersecting;
      syncSticky();
    }, { threshold: 0 }).observe(hero);

    new IntersectionObserver(function (entries) {
      reserveVisible = entries[0].isIntersecting;
      syncSticky();
    }, { threshold: 0.15 }).observe(reserve);

    new IntersectionObserver(function (entries) {
      footerVisible = entries[0].isIntersecting;
      syncSticky();
    }, { threshold: 0 }).observe(footer);
  }

  var engraving = document.getElementById("engraving");
  var engravingCount = document.getElementById("engravingCount");
  if (engraving && engravingCount) {
    engraving.addEventListener("input", function () {
      engravingCount.textContent = engraving.value.length + " / 24";
    });
  }

  var reserveForm = document.getElementById("reserveForm");
  var reserveEmail = document.getElementById("reserveEmail");
  var reserveStatus = document.getElementById("reserveStatus");
  if (reserveForm && reserveEmail && reserveStatus) {
    reserveForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var email = reserveEmail.value.trim();
      var valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);

      if (!valid) {
        reserveEmail.setAttribute("aria-invalid", "true");
        reserveStatus.textContent = "Enter a valid email address to continue.";
        reserveStatus.className = "reserve-status is-error";
        reserveEmail.focus();
        return;
      }

      reserveEmail.removeAttribute("aria-invalid");
      var selectedStrap = reserveForm.querySelector('input[name="strap"]:checked');
      var strap = selectedStrap ? selectedStrap.value : "selected strap";
      reserveStatus.textContent = "Reservation details are ready for " + strap + ". This visual donor preview does not submit or charge.";
      reserveStatus.className = "reserve-status is-success";
    });

    reserveEmail.addEventListener("input", function () {
      if (reserveEmail.getAttribute("aria-invalid") === "true") {
        reserveEmail.removeAttribute("aria-invalid");
        reserveStatus.textContent = "Fully refundable until the watch ships.";
        reserveStatus.className = "reserve-status";
      }
    });
  }
})();
