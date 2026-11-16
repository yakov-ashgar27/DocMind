// Vault UI: PIN prompt, "vault open" indicator. The vault token lives in memory only.
import { api, lockVault, onVaultChange, setVaultToken, vaultUnlocked } from "./api.js";
import { errText, t } from "./i18n.js";
import { render } from "./router.js";
import { h, icon, sheet } from "./ui.js";

let pending = null;

export function promptUnlock() {
  if (pending) return pending;
  pending = new Promise((resolve) => {
    let settled = false;
    const finish = (ok) => { if (!settled) { settled = true; pending = null; resolve(ok); } };
    const err = h("p", { class: "form-error", role: "alert" });
    const input = h("input", { type: "password", inputmode: "numeric", autocomplete: "off", maxlength: 12, pattern: "[0-9]*",
      class: "pin-input", "aria-label": t("enter_pin") });
    const btn = h("button", { class: "btn primary block", type: "submit" }, icon("unlock", 18), t("unlock"));
    const s = sheet(t("enter_pin"), h("form", { class: "form center", onsubmit: async (e) => {
      e.preventDefault();
      btn.disabled = true; err.textContent = "";
      try {
        const r = await api("/vault/unlock", { method: "POST", body: { pin: input.value } });
        setVaultToken(r.vault_token, r.expires_in);
        finish(true);
        s.close();
      } catch (ex) { err.textContent = errText(ex.code); input.value = ""; input.focus(); btn.disabled = false; }
    } }, h("div", { class: "vault-mark" }, icon("lock", 30)), input, err, btn));
    const obs = new MutationObserver(() => { if (!document.body.contains(s.panel)) { obs.disconnect(); finish(false); } });
    obs.observe(document.body, { childList: true });
    setTimeout(() => input.focus(), 50);
  });
  return pending;
}

// Unlock, then re-render the current screen so protected items appear.
export async function unlockAndRefresh() {
  if (await promptUnlock()) render();
}

let pill = null;
export function mountVaultIndicator() {
  onVaultChange((open) => {
    pill?.remove();
    pill = null;
    if (open) {
      pill = h("div", { class: "vault-pill", role: "status" }, icon("unlock", 15), t("vault_open"),
        h("button", { onclick: () => { lockVault(); render(); } }, icon("lock", 14), t("lock_now")));
      document.body.appendChild(pill);
    } else {
      render();
    }
  });
}

export { vaultUnlocked };
