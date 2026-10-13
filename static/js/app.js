// Поведение общих элементов: панель аккаунта, уведомления, поле ссылок, карточки парсинга.
(function () {
  "use strict";

  // Панель аккаунта
  const setDrawer = (open) => {
    document.body.classList.toggle("drawer-open", open);
    document.querySelectorAll("[data-drawer-open]").forEach((b) => b.setAttribute("aria-expanded", String(open)));
  };
  document.querySelectorAll("[data-drawer-open]").forEach((b) => b.addEventListener("click", () => setDrawer(true)));
  document.querySelectorAll("[data-drawer-close]").forEach((b) => b.addEventListener("click", () => setDrawer(false)));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setDrawer(false); });

  // Закрытие уведомлений
  document.querySelectorAll("[data-flash-close]").forEach((b) =>
    b.addEventListener("click", () => b.closest(".flash").remove()));

  // Поле ссылок растёт по содержимому; Enter отправляет, Shift+Enter — новая строка
  document.querySelectorAll("[data-autosize]").forEach((area) => {
    const fit = () => { area.style.height = "auto"; area.style.height = area.scrollHeight + "px"; };
    area.addEventListener("input", fit);
    area.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && area.value.trim()) {
        e.preventDefault();
        area.form.requestSubmit();
      }
    });
    fit();
  });

  // Убрать карточку из результатов парсинга. Карточка определяется ссылкой на товар,
  // а не позицией: после удаления соседних позиции сдвигаются, ссылка — нет.
  document.querySelectorAll("[data-remove-parsed]").forEach((btn) =>
    btn.addEventListener("click", () => {
      fetch(btn.dataset.endpoint, {
        method: "POST",
        body: new URLSearchParams({ source_url: btn.dataset.sourceUrl }),
      }).then((response) => {
        if (!response.ok) return;
        const section = btn.closest("[data-parsed-section]");
        btn.closest(".product-item").remove();
        if (section && !section.querySelector(".product-item")) section.remove();
      });
    }));

  // Кнопки отправки с подтверждением
  document.querySelectorAll("form[data-confirm]").forEach((form) =>
    form.addEventListener("submit", (e) => { if (!confirm(form.dataset.confirm)) e.preventDefault(); }));

  // Блокировка повторной отправки долгих форм (парсинг, обновление цен)
  document.querySelectorAll("form[data-busy]").forEach((form) =>
    form.addEventListener("submit", () => {
      const btn = form.querySelector("button[type=submit], button:not([type])");
      if (btn) { btn.disabled = true; btn.lastChild.textContent = " " + form.dataset.busy; }
    }));
})();
