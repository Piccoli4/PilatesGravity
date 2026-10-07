// Estado de carga en botones de envío + protección contra doble envío.
// Se usa en el sitio público (templates/base.html, accounts/base.html) y en el panel
// de administración (base_admin.html).
(function () {

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
        submitBtn.style.cursor = 'not-allowed';
        submitBtn.innerHTML = `
            <span class="relative z-10 flex items-center justify-center">
                <svg class="animate-spin w-5 h-5 mr-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                </svg>
                ${loadingText}
            </span>
        `;
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
