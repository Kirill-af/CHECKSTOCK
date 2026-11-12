const state = {
  products: [],
  warehouses: [],
  stock: null,
  history: [],
  lastRequestByForm: new Map(),
};

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `key-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = typeof message === "string" ? message : JSON.stringify(message, null, 2);
  el.classList.toggle("error", Boolean(isError));
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 4500);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail = data?.detail ?? data;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.detail
          ? `${detail.detail}${
              detail.alternatives?.length
                ? `\nАльтернативы: ${detail.alternatives
                    .map((a) => `${a.warehouse_name} (${a.available})`)
                    .join(", ")}`
                : ""
            }`
          : JSON.stringify(detail, null, 2);
    throw new Error(message);
  }
  return data;
}

function ensureFormKey(form) {
  const input = form.querySelector("[data-idempotency]");
  if (input && !input.value) input.value = uuid();
  return input?.value;
}

function rotateFormKey(form) {
  const input = form.querySelector("[data-idempotency]");
  if (input) input.value = uuid();
}

function setReplayEnabled(form, enabled) {
  const btn = form.querySelector("[data-replay]");
  if (btn) btn.disabled = !enabled;
}

function rememberRequest(form, path, payload) {
  state.lastRequestByForm.set(form.id, { path, payload: { ...payload } });
  setReplayEnabled(form, true);
}

function fillSelects() {
  document.querySelectorAll("[data-products]").forEach((select) => {
    const current = select.value;
    select.innerHTML = state.products
      .map((p) => `<option value="${p.id}">${p.sku} — ${p.name}</option>`)
      .join("");
    if (current) select.value = current;
  });

  document.querySelectorAll("[data-warehouses-active]").forEach((select) => {
    const current = select.value;
    const active = state.warehouses.filter((w) => w.is_active);
    select.innerHTML = active.map((w) => `<option value="${w.id}">${w.name}</option>`).join("");
    if (current) select.value = current;
  });
}

function renderStock() {
  const stock = state.stock;
  const thead = document.querySelector("#stockTable thead");
  const tbody = document.querySelector("#stockTable tbody");
  if (!stock) return;

  const activeAndDeleted = stock.warehouses;
  thead.innerHTML = `
    <tr>
      <th>Артикул</th>
      <th>Товар</th>
      ${activeAndDeleted
        .map(
          (w) =>
            `<th>${w.name}${w.is_active ? "" : ' <span class="badge deleted">удалён</span>'}
            <span class="sub">на складе / доступно / резерв</span></th>`
        )
        .join("")}
      <th>Итого<br/><span class="sub">на складе / доступно / резерв</span></th>
      <th>В пути ФФ</th>
      <th>В пути FBO</th>
      <th>К клиенту FBS</th>
    </tr>`;

  tbody.innerHTML = stock.products
    .map((p) => {
      const cells = p.balances
        .map(
          (b) => `<td class="num">
            ${b.on_hand} / ${b.available} / ${b.reserved_fbs}
            ${b.warehouse_active ? "" : '<span class="sub">числится на удалённом ФФ</span>'}
          </td>`
        )
        .join("");
      return `<tr>
        <td><strong>${p.sku}</strong></td>
        <td>${p.name}</td>
        ${cells}
        <td class="num">${p.total_on_hand} / ${p.total_available} / ${p.total_reserved_fbs}</td>
        <td class="num">${p.in_transit_ff}</td>
        <td class="num">${p.in_transit_fbo}</td>
        <td class="num">${p.in_transit_fbs}</td>
      </tr>`;
    })
    .join("");
}

function renderTransit() {
  const body = document.getElementById("transitBody");
  const rows = state.stock?.transit || [];
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7" class="muted">Нет активных отправок</td></tr>`;
    return;
  }
  const typeLabel = {
    ff_transfer: "Между ФФ",
    fbo: "FBO → МП",
    fbs_to_customer: "FBS → клиент",
  };
  body.innerHTML = rows
    .map((t) => {
      let action = "—";
      if (t.transit_type === "ff_transfer") {
        action = `<button class="small" data-receive-ff="${t.id}" type="button">Принять на ФФ</button>`;
      } else if (t.transit_type === "fbo") {
        action = `<button class="small" data-receive-fbo="${t.id}" type="button">Принять на МП</button>`;
      }
      return `<tr>
        <td>${t.id}</td>
        <td><span class="badge">${typeLabel[t.transit_type] || t.transit_type}</span></td>
        <td>${t.sku}<span class="sub">${t.product_name}</span></td>
        <td class="num">${t.quantity}</td>
        <td>${t.from_warehouse_name || "—"}</td>
        <td>${t.to_warehouse_name || (t.transit_type === "fbo" ? "Склад МП" : t.transit_type === "fbs_to_customer" ? "Клиент" : "—")}</td>
        <td>${action}</td>
      </tr>`;
    })
    .join("");
}

function renderWarehouses() {
  const body = document.getElementById("warehousesBody");
  body.innerHTML = state.warehouses
    .map((w) => {
      if (!w.is_active) {
        return `<tr>
          <td>${w.id}</td>
          <td>${w.name}</td>
          <td><span class="badge deleted">удалён</span></td>
          <td class="muted">остатки сохранены</td>
        </tr>`;
      }
      return `<tr>
        <td>${w.id}</td>
        <td>${w.name}</td>
        <td><span class="badge ok">активен</span></td>
        <td class="actions">
          <button class="secondary small" data-rename="${w.id}" type="button">Переименовать</button>
          <button class="danger small" data-delete="${w.id}" type="button">Удалить</button>
        </td>
      </tr>`;
    })
    .join("");
}

function renderHistory() {
  const body = document.getElementById("historyBody");
  body.innerHTML = state.history
    .map(
      (op) => `<tr>
        <td>${op.id}</td>
        <td>${op.type}</td>
        <td>${op.sku ? `${op.sku}<span class="sub">${op.product_name || ""}</span>` : "—"}</td>
        <td class="num">${op.quantity}</td>
        <td>${op.from_warehouse_name || "—"}</td>
        <td>${op.to_warehouse_name || "—"}</td>
        <td><code>${op.idempotency_key}</code></td>
        <td>${new Date(op.created_at).toLocaleString()}</td>
      </tr>`
    )
    .join("");
}

async function refresh() {
  const [stock, products, warehouses, history] = await Promise.all([
    api("/api/stock"),
    api("/api/products"),
    api("/api/warehouses?include_deleted=true"),
    api("/api/operations?limit=100"),
  ]);
  state.stock = stock;
  state.products = products;
  state.warehouses = warehouses;
  state.history = history;
  fillSelects();
  renderStock();
  renderTransit();
  renderWarehouses();
  renderHistory();
}

function formPayload(form) {
  ensureFormKey(form);
  const data = Object.fromEntries(new FormData(form).entries());
  ["product_id", "warehouse_id", "from_warehouse_id", "to_warehouse_id", "quantity"].forEach((k) => {
    if (data[k] !== undefined) data[k] = Number(data[k]);
  });
  return data;
}

async function submitOperation(form, path, payload, successText) {
  const op = await api(path, { method: "POST", body: JSON.stringify(payload) });
  rememberRequest(form, path, payload);
  if (op.reused) {
    toast(`Повтор: операция #${op.id} уже была применена, остатки не изменились`);
  } else {
    toast(`${successText} #${op.id}`);
    rotateFormKey(form);
  }
  await refresh();
  return op;
}

document.getElementById("opTabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === btn));
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  document.getElementById(`panel-${btn.dataset.panel}`).classList.add("active");
});

document.querySelectorAll("[data-replay]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const form = btn.closest("form");
    const last = state.lastRequestByForm.get(form.id);
    if (!last) {
      toast("Сначала выполните операцию", true);
      return;
    }
    try {
      const op = await api(last.path, {
        method: "POST",
        body: JSON.stringify(last.payload),
      });
      toast(
        op.reused
          ? `Идемпотентность: повтор с тем же ключом, операция #${op.id}, остатки не изменились`
          : `Операция выполнена #${op.id}`
      );
      await refresh();
    } catch (err) {
      toast(err.message, true);
    }
  });
});

document.getElementById("refreshBtn").addEventListener("click", () => {
  refresh().then(() => toast("Данные обновлены")).catch((err) => toast(err.message, true));
});

document.getElementById("receiptForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = formPayload(e.target);
    await submitOperation(e.target, "/api/operations/receipt", payload, "Приход оформлен");
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("transferForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = formPayload(e.target);
    await submitOperation(
      e.target,
      "/api/operations/transfer/ship",
      payload,
      "Перемещение отправлено"
    );
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("fbsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = formPayload(e.target);
    const action = payload.action;
    delete payload.action;
    const path =
      action === "reserve"
        ? "/api/operations/fbs/reserve"
        : action === "cancel"
          ? "/api/operations/fbs/cancel"
          : "/api/operations/fbs/ship";
    await submitOperation(e.target, path, payload, `FBS ${action}`);
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("fboForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = formPayload(e.target);
    await submitOperation(e.target, "/api/operations/fbo/ship", payload, "FBO отправлено");
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("warehouseCreateForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const name = new FormData(e.target).get("name");
    await api("/api/warehouses", { method: "POST", body: JSON.stringify({ name, shop_id: 1 }) });
    e.target.reset();
    toast("Склад добавлен");
    await refresh();
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("warehousesBody").addEventListener("click", async (e) => {
  const renameId = e.target.dataset.rename;
  const deleteId = e.target.dataset.delete;
  try {
    if (renameId) {
      const name = prompt("Новое название ФФ");
      if (!name) return;
      await api(`/api/warehouses/${renameId}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      toast("Склад переименован");
      await refresh();
    }
    if (deleteId) {
      if (!confirm("Удалить ФФ? Остатки и история сохранятся.")) return;
      const key = uuid();
      const result = await api(`/api/warehouses/${deleteId}?idempotency_key=${encodeURIComponent(key)}`, {
        method: "DELETE",
      });
      toast(result.detail);
      await refresh();
    }
  } catch (err) {
    toast(err.message, true);
  }
});

document.getElementById("transitBody").addEventListener("click", async (e) => {
  const ffId = e.target.dataset.receiveFf;
  const fboId = e.target.dataset.receiveFbo;
  try {
    if (ffId) {
      const op = await api("/api/operations/transfer/receive", {
        method: "POST",
        body: JSON.stringify({ idempotency_key: uuid(), transit_id: Number(ffId) }),
      });
      toast(`Приёмка перемещения #${op.id}`);
      await refresh();
    }
    if (fboId) {
      const op = await api("/api/operations/fbo/receive", {
        method: "POST",
        body: JSON.stringify({ idempotency_key: uuid(), transit_id: Number(fboId) }),
      });
      toast(`Приёмка FBO #${op.id}`);
      await refresh();
    }
  } catch (err) {
    toast(err.message, true);
  }
});

document.querySelectorAll("form").forEach((form) => {
  if (form.querySelector("[data-idempotency]")) rotateFormKey(form);
});

refresh().catch((err) => toast(err.message, true));
