// Avisos push en este dispositivo: el bloque para activarlos, probarlos y desactivarlos.
// Lo usan el panel (campana) y la cuenta del alumno ("Mis reservas"); cada plantilla
// pone sus textos en el bloque [data-push]:
//   data-clave, data-csrf, data-activar, data-desactivar, data-probar (rutas)
//   data-titulo, data-titulo-activo, data-texto-inactivo, data-texto-activo
// El envío lo hace gravity/push.py y la notificación la muestra el service worker (/sw.js).
(function () {
    'use strict';

    const caja = document.querySelector('[data-push]');
    if (!caja) return;

    const titulo = caja.querySelector('[data-push-titulo]');
    const texto = caja.querySelector('[data-push-texto]');
    const btnActivar = caja.querySelector('[data-push-activar]');
    const btnProbar = caja.querySelector('[data-push-probar]');
    const btnDesactivar = caja.querySelector('[data-push-desactivar]');
    const SINCRONIZADO = 'push-sincronizado';

    const TITULO = caja.dataset.titulo || 'Avisos en este dispositivo';
    const TITULO_ACTIVO = caja.dataset.tituloActivo || 'Avisos activados en este dispositivo';
    const TEXTO_INACTIVO = caja.dataset.textoInactivo || '';
    const TEXTO_ACTIVO = caja.dataset.textoActivo || '';

    let registro = null;

    const ua = navigator.userAgent || '';
    const esIOS = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const instalada = window.navigator.standalone === true ||
        (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);
    const soporta = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

    function mostrar(estado, mensaje) {
        caja.hidden = false;
        caja.classList.toggle('is-on', estado === 'activo');
        titulo.textContent = estado === 'activo' ? TITULO_ACTIVO : TITULO;
        texto.textContent = mensaje || '';
        btnActivar.hidden = estado !== 'inactivo';
        btnProbar.hidden = estado !== 'activo';
        btnDesactivar.hidden = estado !== 'activo';
        [btnActivar, btnProbar, btnDesactivar].forEach(function (b) { b.disabled = false; });
    }

    function enviar(url, datos) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': caja.dataset.csrf, 'Content-Type': 'application/json' },
            body: JSON.stringify(datos || {})
        }).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (cuerpo) {
                if (!r.ok || !cuerpo.ok) throw new Error(cuerpo.error || '');
                return cuerpo;
            });
        });
    }

    function claveEnBytes(clave) {
        const relleno = '='.repeat((4 - clave.length % 4) % 4);
        const crudo = atob((clave + relleno).replace(/-/g, '+').replace(/_/g, '/'));
        const bytes = new Uint8Array(crudo.length);
        for (let i = 0; i < crudo.length; i++) bytes[i] = crudo.charCodeAt(i);
        return bytes;
    }

    // ¿La suscripción guardada en el navegador se hizo con la clave actual del servidor?
    function mismaClave(suscripcion) {
        const usada = suscripcion.options && suscripcion.options.applicationServerKey;
        if (!usada) return true;
        const a = new Uint8Array(usada), b = claveEnBytes(caja.dataset.clave);
        if (a.length !== b.length) return false;
        for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
        return true;
    }

    function recordarSincronizado(valor) {
        try {
            if (valor) sessionStorage.setItem(SINCRONIZADO, '1');
            else sessionStorage.removeItem(SINCRONIZADO);
        } catch (err) { /* sin sessionStorage: se sincroniza en cada página */ }
    }

    function yaSincronizado() {
        try { return sessionStorage.getItem(SINCRONIZADO) === '1'; } catch (err) { return false; }
    }

    function revisar() {
        if (!soporta) {
            if (esIOS && !instalada) {
                mostrar('aviso', 'En iPhone, primero agregá la app a la pantalla de inicio: tocá Compartir y elegí "Agregar a inicio". Abrila desde ese ícono y activá los avisos acá.');
            } else {
                mostrar('aviso', 'Este navegador no permite avisos. Probá con Chrome o actualizá el sistema del celular.');
            }
            return;
        }
        if (Notification.permission === 'denied') {
            mostrar('aviso', 'Los avisos están bloqueados para este sitio. Habilitá las notificaciones desde la configuración del navegador y volvé a entrar.');
            return;
        }

        navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' })
            .then(function () { return navigator.serviceWorker.ready; })
            .then(function (reg) {
                registro = reg;
                return reg.pushManager.getSubscription();
            })
            .then(function (suscripcion) {
                if (suscripcion && !mismaClave(suscripcion)) {
                    // Las claves del servidor cambiaron: esa suscripción ya no recibe nada
                    return suscripcion.unsubscribe().then(function () { return null; });
                }
                return suscripcion;
            })
            .then(function (suscripcion) {
                if (!suscripcion) {
                    recordarSincronizado(false);
                    mostrar('inactivo', TEXTO_INACTIVO);
                    return;
                }
                mostrar('activo', TEXTO_ACTIVO);
                // Una vez por sesión se confirma con el servidor (por si cambió quién usa este celular)
                if (!yaSincronizado()) {
                    enviar(caja.dataset.activar, suscripcion.toJSON())
                        .then(function () { recordarSincronizado(true); })
                        .catch(function () {});
                }
            })
            .catch(function () {
                mostrar('aviso', 'No pudimos revisar los avisos en este dispositivo. Recargá la página.');
            });
    }

    function suscribir() {
        return registro.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: claveEnBytes(caja.dataset.clave)
        });
    }

    btnActivar.addEventListener('click', function () {
        if (!registro) return;
        btnActivar.disabled = true;
        // El permiso se pide acá, como respuesta directa al toque (lo exige el iPhone)
        Promise.resolve(Notification.requestPermission())
            .then(function (permiso) {
                if (permiso !== 'granted') {
                    const error = new Error('permiso');
                    error.permiso = permiso;
                    throw error;
                }
                return suscribir();
            })
            .then(function (suscripcion) {
                return enviar(caja.dataset.activar, suscripcion.toJSON()).catch(function (err) {
                    // Si el servidor no la guardó, no tiene sentido dejarla activa en el navegador
                    return suscripcion.unsubscribe().catch(function () {}).then(function () { throw err; });
                });
            })
            .then(function () {
                recordarSincronizado(true);
                mostrar('activo', 'Listo. Tocá "Enviar una prueba" para ver cómo llegan.');
            })
            .catch(function (err) {
                if (err && err.permiso === 'denied') {
                    mostrar('aviso', 'Los avisos quedaron bloqueados para este sitio. Habilitá las notificaciones desde la configuración del navegador y volvé a entrar.');
                } else if (err && err.permiso) {
                    mostrar('inactivo', 'Para activarlos tenés que aceptar el permiso de notificaciones.');
                } else {
                    mostrar('inactivo', 'No se pudieron activar. Si usás Brave, activá "Usar servicios de Google para mensajería push" en su configuración de privacidad y probá de nuevo.');
                }
            });
    });

    btnProbar.addEventListener('click', function () {
        btnProbar.disabled = true;
        enviar(caja.dataset.probar)
            .then(function () { mostrar('activo', 'Te mandamos un aviso de prueba. Tiene que aparecer en unos segundos.'); })
            .catch(function (err) { mostrar('activo', err.message || 'No se pudo enviar la prueba. Probá de nuevo.'); });
    });

    btnDesactivar.addEventListener('click', function () {
        if (!registro) return;
        btnDesactivar.disabled = true;
        registro.pushManager.getSubscription()
            .then(function (suscripcion) {
                if (!suscripcion) return null;
                return enviar(caja.dataset.desactivar, { endpoint: suscripcion.endpoint })
                    .catch(function () {})
                    .then(function () { return suscripcion.unsubscribe(); });
            })
            .then(function () {
                recordarSincronizado(false);
                mostrar('inactivo', 'Avisos desactivados en este dispositivo.');
            })
            .catch(function () { mostrar('activo', 'No se pudieron desactivar. Probá de nuevo.'); });
    });

    revisar();
})();
