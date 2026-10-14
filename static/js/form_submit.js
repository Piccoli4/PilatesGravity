// Estado de carga en botones de envío + protección contra doble envío.
// Se usa en el sitio público (templates/base.html y las páginas de cuenta) y en el panel
// de administración (base_admin.html).
(function () {

    // Estilos propios del spinner: no dependen de Tailwind, así funciona igual en
    // las páginas nuevas (gravity_ui / auth) y en las viejas.
    const estilos = document.createElement('style');
    estilos.textContent =
        '.fs-loading{display:inline-flex;align-items:center;justify-content:center;gap:10px;position:relative;z-index:1}' +
        '.fs-spin{flex:none;width:1.05em;height:1.05em;border-radius:50%;border:2px solid currentColor;' +
        'border-right-color:transparent;opacity:.85;animation:fs-spin .7s linear infinite}' +
        '@keyframes fs-spin{to{transform:rotate(360deg)}}' +
        '@media (prefers-reduced-motion:reduce){.fs-spin{animation-duration:1.6s}}';
    document.head.appendChild(estilos);

    function esPost(form) {
        return (form.getAttribute('method') || 'get').toLowerCase() === 'post';
    }

    // Un POST que se envía dos veces (doble toque, o volver a tocar porque el servidor
    // tarda) puede ejecutar dos veces la misma acción. Bloqueamos también form.submit(),
    // que usan los flujos con modal de confirmación y no dispara el evento 'submit'.
    const submitNativo = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {
        if (esPost(this)) {
            if (this.dataset.enviando) return;
            this.dataset.enviando = '1';
        }
        return submitNativo.call(this);
    };

    document.addEventListener('submit', function (e) {
        // La página canceló el envío (validación propia, confirm(), modal, etc.)
        if (e.defaultPrevented) return;

        const form = e.target;

        if (esPost(form)) {
            if (form.dataset.enviando) {
                e.preventDefault();
                return;
            }
            form.dataset.enviando = '1';
        }

        const submitBtn = e.submitter || form.querySelector('[type="submit"]');
        // Sin botón, o la página ya maneja su propio estado de carga
        if (!submitBtn || submitBtn.disabled) return;

        // Un botón deshabilitado no envía su name/value (ej. name="accion"):
        // lo preservamos en un campo oculto antes de deshabilitarlo.
        if (submitBtn.name) {
            const oculto = document.createElement('input');
            oculto.type = 'hidden';
            oculto.name = submitBtn.name;
            oculto.value = submitBtn.value;
            oculto.dataset.submitterClon = '1';
            form.appendChild(oculto);
        }

        const loadingText = submitBtn.dataset.loadingText || 'Cargando...';

        submitBtn.dataset.originalHtml = submitBtn.innerHTML;
        submitBtn.dataset.originalStyle = submitBtn.getAttribute('style') || '';
        submitBtn.disabled = true;
        submitBtn.style.opacity = '0.75';
        submitBtn.style.cursor = 'wait';
        submitBtn.innerHTML =
            '<span class="fs-loading"><span class="fs-spin" aria-hidden="true"></span>' +
            '<span>' + loadingText + '</span></span>';
    });

    // Al volver con "atrás", el navegador puede restaurar la página desde caché
    // con los botones todavía deshabilitados: los restauramos.
    window.addEventListener('pageshow', function (e) {
        if (!e.persisted) return;

        document.querySelectorAll('form[data-enviando]').forEach(function (form) {
            delete form.dataset.enviando;
        });
        document.querySelectorAll('input[data-submitter-clon]').forEach(function (input) {
            input.remove();
        });
        document.querySelectorAll('[type="submit"][data-original-html]').forEach(function (btn) {
            btn.disabled = false;
            btn.innerHTML = btn.dataset.originalHtml;
            btn.setAttribute('style', btn.dataset.originalStyle || '');
            delete btn.dataset.originalHtml;
            delete btn.dataset.originalStyle;
        });
    });

})();
