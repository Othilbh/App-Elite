// Visualizador de PDF central do Elite Hapkido.
//
// Qualquer <form data-pdf> ou <a data-pdf> do app abre o PDF numa camada
// por cima da tela atual, sem sair dela. Assim a tela anterior continua
// exatamente como estava (filtros, períodos, campos preenchidos, rolagem).
//
// - Botão ✕ fecha e volta para a tela.
// - Botão/gesto de voltar do celular também fecha o PDF (history.pushState).
// - Dá para abrir e fechar vários PDFs seguidos, sem reiniciar o app.
// - O PDF é desenhado com pdf.js (servido pelo próprio app, em
//   /static/vendor/pdfjs). Se o pdf.js falhar, cai para o leitor do navegador.
// - A geração dos PDFs no servidor não muda: o visualizador só busca o
//   mesmo arquivo que antes era baixado.
(function () {
  "use strict";

  var PDFJS_SRC = "/static/vendor/pdfjs/pdf.min.js";
  var PDFJS_WORKER = "/static/vendor/pdfjs/pdf.worker.min.js";

  var overlay, body, titleEl, shareBtn, zoomLabel;
  var state = null; // { blob, url, filename, doc, scale, scrollY, pushed, token }
  var pdfjsPromise = null;
  var openToken = 0;

  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    if (pdfjsPromise) return pdfjsPromise;
    pdfjsPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = PDFJS_SRC;
      s.onload = function () {
        if (!window.pdfjsLib) return reject(new Error("pdf.js indisponível"));
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
        resolve(window.pdfjsLib);
      };
      s.onerror = function () {
        pdfjsPromise = null;
        reject(new Error("pdf.js não carregou"));
      };
      document.head.appendChild(s);
    });
    return pdfjsPromise;
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  function buildOverlay() {
    if (overlay) return;
    overlay = el("div", "pdfv");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Visualizador de PDF");
    overlay.hidden = true;

    var bar = el("div", "pdfv-bar");
    var closeBtn = el("button", "pdfv-btn pdfv-close", "✕");
    closeBtn.type = "button";
    closeBtn.setAttribute("aria-label", "Fechar PDF e voltar");
    closeBtn.addEventListener("click", requestClose);

    titleEl = el("span", "pdfv-title", "PDF");

    var actions = el("div", "pdfv-actions");
    var zoomOut = el("button", "pdfv-btn", "−");
    zoomOut.type = "button";
    zoomOut.setAttribute("aria-label", "Diminuir zoom");
    zoomOut.addEventListener("click", function () { zoom(-0.25); });
    zoomLabel = el("span", "pdfv-zoom", "100%");
    var zoomIn = el("button", "pdfv-btn", "+");
    zoomIn.type = "button";
    zoomIn.setAttribute("aria-label", "Aumentar zoom");
    zoomIn.addEventListener("click", function () { zoom(0.25); });

    shareBtn = el("button", "pdfv-btn pdfv-text", "Compartilhar");
    shareBtn.type = "button";
    shareBtn.addEventListener("click", sharePdf);
    var dlBtn = el("button", "pdfv-btn pdfv-text", "Baixar");
    dlBtn.type = "button";
    dlBtn.addEventListener("click", downloadPdf);

    actions.appendChild(zoomOut);
    actions.appendChild(zoomLabel);
    actions.appendChild(zoomIn);
    actions.appendChild(shareBtn);
    actions.appendChild(dlBtn);

    bar.appendChild(closeBtn);
    bar.appendChild(titleEl);
    bar.appendChild(actions);

    body = el("div", "pdfv-body");
    overlay.appendChild(bar);
    overlay.appendChild(body);
    document.body.appendChild(overlay);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && state) requestClose();
    });
  }

  function setMessage(text, isError) {
    body.innerHTML = "";
    var p = el("p", "pdfv-msg" + (isError ? " pdfv-error" : ""), text);
    body.appendChild(p);
  }

  function filenameFrom(response, fallbackUrl) {
    var cd = response.headers.get("Content-Disposition") || "";
    var m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
    if (m) {
      try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
    }
    var path = (fallbackUrl || "").split("?")[0].split("/").pop();
    return path && path.indexOf(".pdf") > -1 ? path : "documento.pdf";
  }

  function lockPage() {
    state.scrollY = window.scrollY || window.pageYOffset || 0;
    document.documentElement.classList.add("pdfv-open");
  }

  function unlockPage(scrollY) {
    document.documentElement.classList.remove("pdfv-open");
    window.scrollTo(0, scrollY || 0);
  }

  function open(url, trigger) {
    buildOverlay();
    var token = ++openToken;
    var busy = setBusy(trigger);

    // Se já havia um PDF aberto, troca o conteúdo sem empilhar histórico.
    var alreadyOpen = !!state;
    if (alreadyOpen) {
      releaseDoc();
    } else {
      state = { pushed: false, scrollY: 0 };
      lockPage();
      try {
        history.pushState({ pdfViewer: true }, "");
        state.pushed = true;
      } catch (e) { /* sem histórico: o ✕ ainda fecha */ }
    }
    state.token = token;
    state.scale = 1;
    zoomLabel.textContent = "100%";
    titleEl.textContent = "Gerando PDF…";
    shareBtn.hidden = true;
    overlay.hidden = false;
    setMessage("Gerando PDF…");

    function done() { busy(); }

    fetch(url, { credentials: "same-origin", headers: { Accept: "application/pdf" } })
      .then(function (resp) {
        var type = (resp.headers.get("Content-Type") || "").toLowerCase();
        if (!resp.ok || type.indexOf("application/pdf") === -1) {
          // O servidor respondeu com uma página (ex.: aviso de erro ou login).
          // Fecha o visualizador e mostra essa página normalmente.
          var target = resp.redirected ? resp.url : null;
          throw { redirectTo: target, message: "Não consegui gerar o PDF agora. Tente novamente." };
        }
        return resp.blob().then(function (blob) {
          return { blob: blob, filename: filenameFrom(resp, url) };
        });
      })
      .then(function (r) {
        if (!state || state.token !== token) return;
        state.blob = r.blob;
        state.filename = r.filename;
        state.url = URL.createObjectURL(r.blob);
        titleEl.textContent = r.filename;
        shareBtn.hidden = !canShareFile();
        return render();
      })
      .catch(function (err) {
        if (!state || state.token !== token) return;
        if (err && err.redirectTo) {
          // Troca a entrada do visualizador pela página do aviso; o voltar
          // continua levando à tela de antes.
          state.pushed = false;
          close(false);
          window.location.replace(err.redirectTo);
          return;
        }
        titleEl.textContent = "PDF";
        setMessage((err && err.message) || "Não consegui abrir o PDF. Verifique a conexão e tente novamente.", true);
      })
      .then(done, done);
  }

  // Botão que pediu o PDF: mostra "Gerando PDF…" e SEMPRE volta ao normal
  // (deu certo, deu erro ou o usuário fechou antes de terminar).
  function setBusy(btn) {
    if (!btn) return function () {};
    var isInput = btn.tagName === "INPUT";
    var original = btn.getAttribute("data-pdf-label") || (isInput ? btn.value : btn.textContent);
    btn.setAttribute("data-pdf-label", original);
    btn.setAttribute("aria-busy", "true");
    if (btn.tagName !== "A") {
      btn.disabled = true;
      if (isInput) btn.value = "Gerando PDF…"; else btn.textContent = "Gerando PDF…";
    }
    var restored = false;
    return function () {
      if (restored) return;
      restored = true;
      btn.removeAttribute("aria-busy");
      if (btn.tagName !== "A") {
        btn.disabled = false;
        if (isInput) btn.value = original; else btn.textContent = original;
      }
    };
  }

  function render() {
    var token = state.token;
    return loadPdfJs()
      .then(function (pdfjsLib) {
        if (!state || state.token !== token) return;
        if (state.doc) return state.doc;
        return state.blob.arrayBuffer().then(function (buf) {
          return pdfjsLib.getDocument({ data: buf }).promise;
        }).then(function (doc) {
          if (!state || state.token !== token) { doc.destroy(); return null; }
          state.doc = doc;
          return doc;
        });
      })
      .then(function (doc) {
        if (!doc || !state || state.token !== token) return;
        body.innerHTML = "";
        var width = Math.min(body.clientWidth - 16, 900) * state.scale;
        var dpr = Math.min(window.devicePixelRatio || 1, 2);
        var chain = Promise.resolve();
        for (var n = 1; n <= doc.numPages; n++) {
          (function (pageNum) {
            chain = chain.then(function () {
              if (!state || state.token !== token) return;
              return doc.getPage(pageNum).then(function (page) {
                var base = page.getViewport({ scale: 1 });
                var cssScale = width / base.width;
                var viewport = page.getViewport({ scale: cssScale * dpr });
                var canvas = el("canvas", "pdfv-page");
                canvas.width = Math.floor(viewport.width);
                canvas.height = Math.floor(viewport.height);
                canvas.style.width = Math.floor(base.width * cssScale) + "px";
                canvas.style.height = Math.floor(base.height * cssScale) + "px";
                canvas.setAttribute("aria-label", "Página " + pageNum);
                body.appendChild(canvas);
                return page.render({ canvasContext: canvas.getContext("2d"), viewport: viewport }).promise;
              });
            });
          })(n);
        }
        return chain;
      })
      .catch(function () {
        if (!state || state.token !== token) return;
        // Plano B: leitor de PDF do próprio navegador, dentro da camada.
        body.innerHTML = "";
        var frame = el("iframe", "pdfv-frame");
        frame.src = state.url;
        frame.title = state.filename || "PDF";
        body.appendChild(frame);
      });
  }

  function zoom(delta) {
    if (!state || !state.doc) return;
    var next = Math.max(0.5, Math.min(3, Math.round((state.scale + delta) * 100) / 100));
    if (next === state.scale) return;
    state.scale = next;
    zoomLabel.textContent = Math.round(next * 100) + "%";
    render();
  }

  function canShareFile() {
    if (!state || !state.blob || !navigator.canShare || !window.File) return false;
    try {
      var f = new File([state.blob], state.filename, { type: "application/pdf" });
      return navigator.canShare({ files: [f] });
    } catch (e) {
      return false;
    }
  }

  function sharePdf() {
    if (!state || !state.blob) return;
    var f = new File([state.blob], state.filename, { type: "application/pdf" });
    navigator.share({ files: [f], title: state.filename }).catch(function () {});
  }

  function downloadPdf() {
    if (!state || !state.url) return;
    var a = document.createElement("a");
    a.href = state.url;
    a.download = state.filename || "documento.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function releaseDoc() {
    if (!state) return;
    if (state.doc) { try { state.doc.destroy(); } catch (e) {} }
    if (state.url) URL.revokeObjectURL(state.url);
    state.doc = null;
    state.url = null;
    state.blob = null;
  }

  // ✕ / Esc: volta no histórico, o que dispara o fechamento (mesmo caminho
  // do botão de voltar do celular).
  function requestClose() {
    if (!state) return;
    if (state.pushed) {
      history.back();
    } else {
      close(false);
    }
  }

  function close(dropHistory) {
    if (!state) return;
    var scrollY = state.scrollY;
    var pushed = state.pushed;
    openToken++;
    releaseDoc();
    state = null;
    overlay.hidden = true;
    body.innerHTML = "";
    unlockPage(scrollY);
    if (dropHistory && pushed) {
      try { history.back(); } catch (e) {}
    }
  }

  window.addEventListener("popstate", function () {
    if (state) {
      state.pushed = false;
      close(false);
    }
  });

  function formUrl(form) {
    var action = form.getAttribute("action") || window.location.href;
    var u = new URL(action, window.location.href);
    var data = new FormData(form);
    data.forEach(function (value, key) {
      if (typeof value === "string") u.searchParams.append(key, value);
    });
    return u.toString();
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.hasAttribute || !form.hasAttribute("data-pdf")) return;
    if ((form.getAttribute("method") || "get").toLowerCase() !== "get") return;
    e.preventDefault();
    open(formUrl(form), form.querySelector('[type="submit"]'));
  });

  document.addEventListener("click", function (e) {
    var link = e.target && e.target.closest ? e.target.closest("a[data-pdf]") : null;
    if (!link || e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey) return;
    e.preventDefault();
    open(link.href, link);
  });

  window.ElitePdfViewer = { open: open, close: requestClose };
})();
