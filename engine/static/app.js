/* Progressive enhancement for the server-rendered dashboard. Loaded from
 * 'self' so the strict CSP (no inline scripts) stays intact. */
"use strict";

// Password visibility toggles: any .pw-wrap > input + button.pw-toggle.
document.addEventListener("click", function (event) {
  var btn = event.target.closest(".pw-toggle");
  if (!btn) return;
  var wrap = btn.closest(".pw-wrap");
  var input = wrap && wrap.querySelector("input");
  if (!input) return;
  var show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  btn.title = show ? "Hide password" : "Show password";
  var eye = btn.querySelector(".ico-eye");
  var eyeOff = btn.querySelector(".ico-eye-off");
  if (eye) eye.style.display = show ? "none" : "";
  if (eyeOff) eyeOff.style.display = show ? "" : "none";
  input.focus();
});
