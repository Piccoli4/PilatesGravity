// Panel de administración: hojas ("Más" y notificaciones), avisos, bandeja y
// confirmaciones con el modal del panel en lugar de confirm().
//
// Confirmar antes de una acción: agregá data-confirm="Texto" a un <form>, a su botón
// de envío o a un <a>. Opcionales: data-confirm-titulo, data-confirm-boton y
// data-confirm-peligro (botón rojo). Desde JS: panelConfirmar({...}).then(ok => ...)
(function () {
    'use strict';

    const body = document.body;
    let ultimoFoco = null;

    // ---------------------------------------------------------------- Hojas
    const overlay = document.getElementById('ad-overlay');

    function hojaAbierta() {
        return document.querySelector('.ad-sheet.is-open');
    }

    function abrirHoja(hoja, disparador) {
        const abierta = hojaAbierta();
        if (abierta && abierta !== hoja) cerrarHoja(abierta, false);
        ultimoFoco = disparador || document.activeElement;
        hoja.classList.add('is-open');
        hoja.setAttribute('aria-hidden', 'false');
        overlay.classList.add('is-open');
        body.classList.add('is-locked');
        document.querySelectorAll('[data-abrir="' + hoja.id + '"]').forEach(function (b) {
            b.setAttribute('aria-expanded', 'true');
        });
        const foco = hoja.querySelector('[data-cerrar]') || hoja;
        setTimeout(function () { foco.focus({ preventScroll: true }); }, 60);
        if (hoja.dataset.alAbrir === 'bandeja') marcarBandejaVista();
    }

    function cerrarHoja(hoja, devolverFoco) {
        if (!hoja) return;
        hoja.classList.remove('is-open');
        hoja.setAttribute('aria-hidden', 'true');
        overlay.classList.remove('is-open');
        body.classList.remove('is-locked');
        document.querySelectorAll('[data-abrir="' + hoja.id + '"]').forEach(function (b) {
            b.setAttribute('aria-expanded', 'false');
        });
        if (devolverFoco !== false && ultimoFoco) ultimoFoco.focus({ preventScroll: true });
    }

    document.addEventListener('click', function (e) {
        const abrir = e.target.closest('[data-abrir]');
        if (abrir) {
            const hoja = document.getElementById(abrir.dataset.abrir);
            if (!hoja) return;
            e.preventDefault();
            if (hoja.classList.contains('is-open')) cerrarHoja(hoja);
            else abrirHoja(hoja, abrir);
            return;
        }
        if (e.target.closest('[data-cerrar]')) {
            cerrarHoja(e.target.closest('.ad-sheet'));
        }
    });

    if (overlay) overlay.addEventListener('click', function () { cerrarHoja(hojaAbierta()); });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (modal && modal.classList.contains('is-open')) return; // lo maneja el modal
        const hoja = hojaAbierta();
        if (hoja) cerrarHoja(hoja);
    });

    // En escritorio "Más" no existe: si se agranda la ventana con la hoja abierta, se cierra
    window.addEventListener('resize', function () {
        const hoja = hojaAbierta();
        if (hoja && hoja.id === 'ad-mas' && window.innerWidth >= 1024) cerrarHoja(hoja, false);
    });

    // -------------------------------------------------------------- Bandeja
    // Al abrir la bandeja se marca todo como visto: el número desaparece, pero la
    // lista queda a la vista hasta recargar la página.
    let bandejaMarcada = false;

    function marcarBandejaVista() {
        const bandeja = document.getElementById('ad-bandeja');
        if (!bandeja || bandejaMarcada || bandeja.dataset.sinLeer === '0') return;
        bandejaMarcada = true;
        let ids = [];
        try { ids = JSON.parse(bandeja.dataset.sueltas || '[]'); } catch (err) { ids = []; }
        fetch(bandeja.dataset.url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': bandeja.dataset.csrf, 'Content-Type': 'application/json' },
            body: JSON.stringify({ recupero_ids: ids })
        }).then(function (r) {
            if (!r.ok) throw new Error(r.status);
            document.querySelectorAll('[data-bandeja-dot]').forEach(function (d) { d.remove(); });
            bandeja.dataset.sinLeer = '0';
            bandeja.querySelector('.ad-inbox').classList.add('is-read');
        }).catch(function () {
            bandejaMarcada = false; // se vuelve a intentar la próxima vez que se abra
        });
    }

    // --------------------------------------------------------------- Avisos
    const avisos = document.querySelectorAll('.pg-message');
    if (avisos.length) {
        setTimeout(function () {
            avisos.forEach(function (m) {
                m.classList.add('is-leaving');
                setTimeout(function () { m.remove(); }, 500);
            });
        }, 7000);
    }

    // ---------------------------------------------------------- Confirmación
    const modal = document.getElementById('ad-confirm');
    let resolver = null;

    function cerrarModal(resultado) {
        if (!modal || !resolver) return;
        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');
        if (!hojaAbierta()) body.classList.remove('is-locked');
        const r = resolver;
        resolver = null;
        if (ultimoFoco && ultimoFoco.focus) ultimoFoco.focus({ preventScroll: true });
        r(resultado);
    }

    window.panelConfirmar = function (opciones) {
        opciones = opciones || {};
        if (!modal) return Promise.resolve(window.confirm(opciones.texto || '¿Confirmás?'));
        if (resolver) cerrarModal(false);
        ultimoFoco = document.activeElement;
        modal.querySelector('.ad-modal__title').textContent = opciones.titulo || '¿Confirmás?';
        modal.querySelector('.ad-modal__text').textContent = opciones.texto || '';
        const aceptar = modal.querySelector('[data-modal-aceptar]');
        aceptar.textContent = opciones.boton || 'Confirmar';
        const peligro = !!opciones.peligro;
        modal.classList.toggle('ad-modal--danger', peligro);
        aceptar.classList.toggle('ad-btn--danger', peligro);
        modal.classList.add('is-open');
        modal.setAttribute('aria-hidden', 'false');
        body.classList.add('is-locked');
        setTimeout(function () { aceptar.focus({ preventScroll: true }); }, 60);
        return new Promise(function (resolve) { resolver = resolve; });
    };

    if (modal) {
        modal.addEventListener('click', function (e) {
            if (e.target === modal || e.target.closest('[data-modal-cancelar]')) cerrarModal(false);
            else if (e.target.closest('[data-modal-aceptar]')) cerrarModal(true);
        });
        modal.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { e.preventDefault(); cerrarModal(false); }
            if (e.key === 'Tab') {
                // El foco no sale del modal mientras está abierto
                const botones = modal.querySelectorAll('button');
                const primero = botones[0], ultimo = botones[botones.length - 1];
                if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
                else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
            }
        });
    }

    function opcionesDe(el) {
        return {
            texto: el.dataset.confirm,
            titulo: el.dataset.confirmTitulo,
            boton: el.dataset.confirmBoton,
            peligro: el.dataset.confirmPeligro !== undefined
        };
    }

    // Formularios: se escucha en captura para frenar el envío antes que form_submit.js
    document.addEventListener('submit', function (e) {
        const form = e.target;
        if (form.dataset.confirmado) {
            delete form.dataset.confirmado;
            return;
        }
        const origen = (e.submitter && e.submitter.dataset.confirm !== undefined) ? e.submitter
            : (form.dataset.confirm !== undefined ? form : null);
        if (!origen) return;
        e.preventDefault();
        const submitter = e.submitter;
        window.panelConfirmar(opcionesDe(origen)).then(function (ok) {
            if (!ok) return;
            form.dataset.confirmado = '1';
            if (form.requestSubmit) form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
            else form.submit();
        });
    }, true);

    // -------------------------------------------------------------- Diálogos
    // <button data-dialogo="id" data-accion="/url/" data-rellenar='{"clave": "valor"}'>
    // abre <dialog id="id">, pone la acción del formulario y completa los
    // elementos con data-rellena="clave" (inputs: value; el resto: texto).
    document.addEventListener('click', function (e) {
        const boton = e.target.closest('[data-dialogo]');
        if (boton) {
            const dialogo = document.getElementById(boton.dataset.dialogo);
            if (!dialogo || !dialogo.showModal) return;
            const form = dialogo.querySelector('form');
            if (form) {
                form.reset();
                delete form.dataset.enviando;
                if (boton.dataset.accion) form.action = boton.dataset.accion;
            }
            let datos = {};
            try { datos = JSON.parse(boton.dataset.rellenar || '{}'); } catch (err) { datos = {}; }
            Object.keys(datos).forEach(function (clave) {
                dialogo.querySelectorAll('[data-rellena="' + clave + '"]').forEach(function (el) {
                    if ('value' in el && el.tagName !== 'BUTTON') el.value = datos[clave];
                    else el.textContent = datos[clave];
                });
            });
            ultimoFoco = boton;
            dialogo.showModal();
            dialogo.dispatchEvent(new CustomEvent('panel:abierto'));
            return;
        }
        if (e.target.closest('[data-cerrar-dialogo]')) {
            const dialogo = e.target.closest('dialog');
            if (dialogo) dialogo.close();
        }
    });
    // Tocar fuera de la caja cierra el diálogo
    document.querySelectorAll('dialog.ad-dialog').forEach(function (d) {
        d.addEventListener('click', function (e) { if (e.target === d) d.close(); });
        d.addEventListener('close', function () { if (ultimoFoco && ultimoFoco.focus) ultimoFoco.focus({ preventScroll: true }); });
    });

    // Enlaces con data-confirm
    document.addEventListener('click', function (e) {
        const enlace = e.target.closest('a[data-confirm]');
        if (!enlace) return;
        e.preventDefault();
        window.panelConfirmar(opcionesDe(enlace)).then(function (ok) {
            if (ok) window.location.href = enlace.href;
        });
    }, true);
})();
