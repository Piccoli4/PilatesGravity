/*
 * Ficha de alguien del equipo (panel):
 * - Formularios de turnos: "todas las semanas" o "un día puntual", clases del
 *   sistema u otro horario; las clases se filtran por el día (o el de la fecha).
 * - Diálogo de un turno: "Deshacer" solo si es un cambio cargado; un turno suelto
 *   se quita en lugar de marcarse como no trabajado.
 * - Antes de guardar algo que toca un mes ya pagado, se pide confirmación
 *   (data-eq-pagado en el formulario: "mes:campo", "desde:campo", "despues:campo"
 *   o "auto" para el formulario de turnos).
 */
(function () {
    'use strict';

    const DIAS = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado'];
    const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
        'septiembre', 'octubre', 'noviembre', 'diciembre'];

    function diaDeFecha(valor) {
        if (!valor) return '';
        const p = valor.split('-');
        return DIAS[new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2])).getDay()];
    }

    function marcado(form, nombre) {
        const el = form.querySelector('input[name="' + nombre + '"]:checked');
        return el ? el.value : '';
    }

    function mostrar(el, visible) {
        el.hidden = !visible;
        el.querySelectorAll('input, select').forEach(function (campo) {
            if (campo.name === 'clases') return;
            campo.disabled = !visible || !!campo.closest('[hidden]');
        });
    }

    // ------------------------------------------------ Formularios de turnos
    function prepararTurnos(form) {
        if (!form) return;
        const selectDia = form.querySelector('[data-eq-dia]');
        const selectSede = form.querySelector('[data-eq-sede]');
        const inputFecha = form.querySelector('[data-eq-fecha]');
        const leyenda = form.querySelector('[data-eq-leyenda]');
        const sinClases = form.querySelector('[data-eq-sin-clases]');

        function actualizar() {
            const modo = marcado(form, 'modo') || 'fecha';
            const origen = marcado(form, 'origen') || 'clase';
            form.querySelectorAll('[data-modo]').forEach(function (b) { b.hidden = b.dataset.modo !== modo; });
            form.querySelectorAll('[data-origen]').forEach(function (b) { b.hidden = b.dataset.origen !== origen; });
            form.querySelectorAll('[data-modo], [data-origen]').forEach(function (b) { mostrar(b, !b.hidden); });

            const dia = modo === 'fecha' ? diaDeFecha(inputFecha && inputFecha.value) : (selectDia ? selectDia.value : '');
            const sede = selectSede ? selectSede.value : '';
            let disponibles = 0;
            form.querySelectorAll('.eq-clase').forEach(function (item) {
                const coincide = item.dataset.dia === dia && (!sede || item.dataset.sede === sede);
                item.hidden = !coincide;
                const casilla = item.querySelector('input');
                casilla.disabled = !coincide || origen !== 'clase';
                if (!coincide) casilla.checked = false;
                if (coincide) disponibles += 1;
            });
            if (sinClases) sinClases.hidden = disponibles > 0 || origen !== 'clase';
            if (leyenda) leyenda.textContent = dia ? 'Clases de los ' + dia.toLowerCase() + ': marcá las que va a dar.' : 'Marcá las clases que va a dar.';
        }

        form.addEventListener('change', actualizar);
        form.addEventListener('input', function (e) { if (e.target === inputFecha) actualizar(); });
        form.addEventListener('panel:actualizar', actualizar);
        actualizar();
    }

    prepararTurnos(document.getElementById('eq-form-turnos'));
    prepararTurnos(document.getElementById('eq-form-dia'));

    // Al abrir un diálogo, se ajusta a lo que se rellenó
    const dlgDia = document.getElementById('dlg-dia');
    if (dlgDia) {
        dlgDia.addEventListener('panel:abierto', function () {
            document.getElementById('eq-form-dia').dispatchEvent(new CustomEvent('panel:actualizar'));
        });
    }
    const dlgTurno = document.getElementById('dlg-turno');
    if (dlgTurno) {
        dlgTurno.addEventListener('panel:abierto', function () {
            const ajuste = dlgTurno.querySelector('input[name="ajuste_id"]').value;
            const origen = dlgTurno.querySelector('[data-eq-origen]').value;
            dlgTurno.querySelector('[data-eq-deshacer]').hidden = !ajuste || origen === 'extra';
            dlgTurno.querySelector('[data-eq-no-trabajo]').textContent =
                origen === 'extra' ? 'Quitar este turno suelto' : 'No trabajó este turno';
        });
    }

    // ------------------------------------------- Aviso de mes ya pagado
    const contenedor = document.querySelector('[data-eq-pagados]');
    const pagados = contenedor && contenedor.dataset.eqPagados ? contenedor.dataset.eqPagados.split(',') : [];

    function nombreMes(clave) {
        const p = clave.split('-');
        return MESES[Number(p[1]) - 1] + ' ' + p[0];
    }

    function mesPagadoAfectado(form) {
        let regla = form.dataset.eqPagado;
        if (regla === 'auto') {
            regla = marcado(form, 'modo') === 'fecha' ? 'mes:fecha' : 'desde:vigente_desde';
        }
        const partes = regla.split(':');
        const campo = form.querySelector('[name="' + partes[1] + '"]');
        if (!campo || !campo.value) return '';
        let fecha = campo.value;
        if (partes[0] === 'despues') {
            const p = fecha.split('-');
            const d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]) + 1);
            fecha = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-01';
        }
        const mes = fecha.slice(0, 7);
        if (partes[0] === 'mes') return pagados.indexOf(mes) >= 0 ? mes : '';
        return pagados.filter(function (m) { return m >= mes; })[0] || '';
    }

    document.addEventListener('submit', function (e) {
        const form = e.target;
        if (!form.dataset || !form.dataset.eqPagado || !pagados.length) return;
        if (form.dataset.eqPagadoOk) { delete form.dataset.eqPagadoOk; return; }
        const mes = mesPagadoAfectado(form);
        if (!mes) return;
        e.preventDefault();
        e.stopImmediatePropagation();
        const submitter = e.submitter;
        window.panelConfirmar({
            titulo: 'Este cambio toca un mes pagado',
            texto: 'El pago de ' + nombreMes(mes) + ' ya está registrado. Si guardás, en ese mes vas a ver la diferencia con lo que se pagó.',
            boton: 'Guardar igual',
        }).then(function (ok) {
            if (!ok) return;
            form.dataset.eqPagadoOk = '1';
            if (form.requestSubmit) form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
            else form.submit();
        });
    }, true);
})();
