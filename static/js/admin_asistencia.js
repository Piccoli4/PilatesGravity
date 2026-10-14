/*
 * Asistencia del panel (Pasar lista): marcar "No vino" sin recargar la página.
 * Cada alumno tiene un formulario común (funciona sin JavaScript); acá se manda
 * en JSON y se actualizan la fila, el resumen de la clase y el total del día.
 */
(function () {
    'use strict';

    // "Otra fecha" muestra el selector de fecha
    const botonOtra = document.querySelector('[data-as-otra]');
    const otra = document.getElementById('as-otra');
    if (botonOtra && otra) {
        botonOtra.addEventListener('click', function () {
            otra.hidden = !otra.hidden;
            botonOtra.setAttribute('aria-expanded', String(!otra.hidden));
            if (!otra.hidden) otra.querySelector('input[type="date"]').focus();
        });
    }

    const vivo = document.querySelector('[data-as-vivo]');

    function avisar(texto, tipo) {
        if (vivo) vivo.textContent = texto;
        let caja = document.querySelector('.g-toasts');
        if (!caja) {
            caja = document.createElement('div');
            caja.className = 'g-toasts';
            caja.setAttribute('role', 'status');
            caja.setAttribute('aria-live', 'polite');
            document.body.appendChild(caja);
        }
        caja.querySelectorAll('[data-as-toast]').forEach(function (t) { t.remove(); });
        const toast = document.createElement('div');
        toast.className = 'pg-message g-toast g-toast--' + (tipo === 'error' ? 'error' : 'success');
        toast.dataset.asToast = '';
        const parrafo = document.createElement('p');
        parrafo.className = 'g-toast__text';
        parrafo.textContent = texto;
        toast.appendChild(parrafo);
        caja.appendChild(toast);
        setTimeout(function () {
            toast.classList.add('is-leaving');
            setTimeout(function () { toast.remove(); }, 500);
        }, 3500);
    }

    function actualizarClase(clase) {
        const noVinieron = clase.querySelectorAll('[data-as-alumno].is-no-vino').length;
        const nv = clase.querySelector('[data-as-nv]');
        if (nv) nv.textContent = noVinieron + (noVinieron === 1 ? ' no vino' : ' no vinieron');
        const badge = clase.querySelector('[data-as-nv-badge]');
        if (badge) badge.classList.toggle('is-cero', noVinieron === 0);
        const vinieron = clase.querySelector('[data-as-vinieron]');
        if (vinieron) {
            const anotados = clase.querySelectorAll('[data-as-alumno]:not(.hy-alumno--falta)').length;
            vinieron.textContent = anotados - noVinieron;
        }
        const total = document.querySelector('[data-as-total-nv]');
        if (total) {
            const n = document.querySelectorAll('[data-as-alumno].is-no-vino').length;
            total.textContent = n;
            total.closest('[data-as-kpi]').classList.toggle('pn-kpi--danger', n > 0);
        }
    }

    function aplicarEstado(fila, form, noVino) {
        const nombre = fila.querySelector('.hy-alumno__nombre').textContent.trim();
        const boton = form.querySelector('button');
        fila.classList.toggle('is-no-vino', noVino);
        fila.querySelector('[data-as-marca]').hidden = !noVino;
        form.querySelector('input[name="marcar"]').value = noVino ? '0' : '1';
        boton.textContent = noVino ? 'Deshacer' : 'No vino';
        boton.classList.toggle('pn-btn--ghost', noVino);
        boton.classList.toggle('pn-btn--danger-ghost', !noVino);
        boton.setAttribute('aria-label', noVino ? 'Deshacer: ' + nombre + ' vino' : 'Marcar que ' + nombre + ' no vino');
        actualizarClase(fila.closest('.as-clase'));
    }

    document.querySelectorAll('[data-as-form]').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            const boton = form.querySelector('button');
            if (boton.disabled) return;
            const fila = form.closest('[data-as-alumno]');
            const datos = new FormData(form);
            boton.disabled = true;
            fetch(form.action, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': datos.get('csrfmiddlewaretoken'),
                },
                body: JSON.stringify({
                    reserva_id: datos.get('reserva_id'),
                    fecha: datos.get('fecha'),
                    marcar: datos.get('marcar') === '1',
                }),
            })
                .then(function (r) {
                    return r.json().catch(function () { return { success: false }; });
                })
                .then(function (data) {
                    if (data.success) {
                        aplicarEstado(fila, form, data.estado === 'no_vino');
                        avisar(data.message, 'ok');
                    } else {
                        avisar(data.error || 'No se pudo guardar. Probá de nuevo.', 'error');
                    }
                })
                .catch(function () {
                    avisar('No hay conexión. Probá de nuevo.', 'error');
                })
                .finally(function () {
                    boton.disabled = false;
                });
        });
    });
})();
