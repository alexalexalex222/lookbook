(function () {
  "use strict";

  var form = document.getElementById("orderForm");
  var status = document.getElementById("order-status");
  var mobileNav = document.querySelector(".mobile-nav");

  if (mobileNav) {
    mobileNav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        mobileNav.removeAttribute("open");
      });
    });
  }

  if (!form || !status) return;

  form.addEventListener("submit", function (event) {
    event.preventDefault();

    if (!form.reportValidity()) return;

    var button = form.querySelector('button[type="submit"]');
    var selectedLight = form.querySelector('input[name="light"]:checked');
    var quantity = form.elements.quantity.value;

    button.disabled = true;
    button.textContent = "Reviewing selection...";

    window.setTimeout(function () {
      status.textContent =
        "Preview ready: " +
        quantity +
        " CORE unit, " +
        (selectedLight ? selectedLight.value : "lighting pending") +
        ". Connect verified inventory, price, policies, and checkout before publishing.";
      button.disabled = false;
      button.textContent = "Continue to availability";
      status.focus();
    }, 420);
  });
})();
