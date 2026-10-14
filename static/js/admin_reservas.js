// Reservas del panel ("Reservar para un alumno" y "Cambiar reserva"):
// buscador de alumnos, lugares libres por clase, fechas de recuperos/clases únicas
// y avisos de plan y recuperos. Los datos vienen en <script id="rs-datos"> (clase ->
// {fijos, fechas: [{iso, texto, libres}]}) y <script id="rs-alumnos">.
(function () {
    'use strict';

    function leer(id) {
        const el = document.getElementById(id);
        if (!el) return null;
        try { return JSON.parse(el.textContent); } catch (e) { return null; }
    }

    // ------------------------------------------------------- Buscador de alumnos
    const buscador = document.querySelector('[data-buscador]');
    const alumnos = leer('rs-alumnos') || [];
    if (buscador) {
        const input = buscador.querySelector('input');
        const lista = buscador.querySelector('[data-resultados]');
        const normalizar = function (t) {
            return (t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
        };
        function elegir(id) {
            const url = new URL(window.location.href);
            url.searchParams.set('alumno', id);
            const clase = document.querySelector('[data-picker] input[type="radio"]:checked');
            if (clase) url.searchParams.set('clase', clase.value);
            window.location.href = url.toString();
        }
        function mostrar() {
            const q = normalizar(input.value.trim());
            lista.innerHTML = '';
            if (q.length < 2) { lista.hidden = true; return; }
            const encontrados = alumnos.filter(function (a) {
                return normalizar(a.nombre).indexOf(q) >= 0 || normalizar(a.email).indexOf(q) >= 0;
            }).slice(0, 8);
            if (!encontrados.length) {
                lista.innerHTML = '<li class="rs-res__vacio">No hay alumnos con ese nombre.</li>';
            }
            encontrados.forEach(function (a) {
                const li = document.createElement('li');
                const b = document.createElement('button');
                b.type = 'button';
                b.className = 'rs-res__item';
                b.innerHTML = '<strong></strong><small></small>';
                b.querySelector('strong').textContent = a.nombre;
                b.querySelector('small').textContent = a.email || 'Sin email';
                b.addEventListener('click', function () { elegir(a.id); });
                li.appendChild(b);
                lista.appendChild(li);
            });
            lista.hidden = false;
        }
        input.addEventListener('input', mostrar);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                const primero = lista.querySelector('.rs-res__item');
                if (primero) primero.click();
            }
        });
    }

    // ------------------------------------------------------- Selector de clase
    const picker = document.querySelector('[data-picker]');
    const datos = leer('rs-datos') || {};
    if (!picker) return;
    const form = picker.closest('form');
    const campo = picker.dataset.campo;
    const cajaFechas = form.querySelector('[data-fechas]');
    const listaFechas = form.querySelector('[data-fechas-lista]');
    const ayudaFechas = form.querySelector('[data-fechas-ayuda]');
    const avisos = form.querySelector('[data-avisos]');
    let fechaElegida = picker.dataset.fecha || '';

    function modo() {
        if (picker.dataset.modo) return picker.dataset.modo;
        const tipo = form.querySelector('input[name="tipo_reserva"]:checked');
        return tipo && tipo.value !== 'recurrente' ? 'puntual' : 'fijo';
    }
    function claseElegida() {
        const r = form.querySelector('input[name="' + campo + '"]:checked');
        return r ? r.value : '';
    }
    function plural(n, uno, varios) { return n === 1 ? uno : varios; }

    function actualizarLibres() {
        const m = modo();
        picker.querySelectorAll('.rs-op').forEach(function (op) {
            const input = op.querySelector('input');
            const d = datos[input.value] || { fijos: 0, fechas: [] };
            const etiqueta = op.querySelector('[data-libres]');
            let disponible;
            if (m === 'fijo') {
                disponible = d.fijos > 0;
                etiqueta.textContent = disponible ? d.fijos + ' ' + plural(d.fijos, 'libre', 'libres') : 'Completa';
            } else {
                const conLugar = d.fechas.filter(function (f) { return f.libres > 0; }).length;
                disponible = conLugar > 0;
                etiqueta.textContent = disponible ? 'Lugar en ' + conLugar + ' de ' + d.fechas.length + ' fechas' : 'Sin lugar';
            }
            op.classList.toggle('is-llena', !disponible);
            input.disabled = !disponible;
            if (!disponible && input.checked) input.checked = false;
        });
    }

    function actualizarFechas() {
        if (!cajaFechas) return;
        const puntual = modo() === 'puntual';
        cajaFechas.hidden = !puntual;
        listaFechas.innerHTML = '';
        const id = claseElegida();
        if (!puntual) return;
        if (!id) { ayudaFechas.hidden = false; return; }
        ayudaFechas.hidden = true;
        const fechas = (datos[id] || {}).fechas || [];
        let marcada = fechas.some(function (f) { return f.iso === fechaElegida && f.libres > 0; });
        fechas.forEach(function (f) {
            const label = document.createElement('label');
            label.className = 'rs-fecha' + (f.libres > 0 ? '' : ' is-llena');
            const input = document.createElement('input');
            input.type = 'radio';
            input.name = 'fecha';
            input.value = f.iso;
            input.disabled = f.libres <= 0;
            if ((marcada && f.iso === fechaElegida) || (!marcada && f.libres > 0)) {
                input.checked = true;
                marcada = true;
                fechaElegida = f.iso;
            }
            input.addEventListener('change', function () { fechaElegida = f.iso; });
            const span = document.createElement('span');
            span.innerHTML = '<strong></strong><small></small>';
            span.querySelector('strong').textContent = f.texto;
            span.querySelector('small').textContent = f.libres > 0 ? f.libres + ' ' + plural(f.libres, 'libre', 'libres') : 'Completa';
            label.appendChild(input);
            label.appendChild(span);
            listaFechas.appendChild(label);
        });
    }

    function actualizarAvisos() {
        if (!avisos) return;
        const tipo = form.querySelector('input[name="tipo_reserva"]:checked');
        const t = tipo ? tipo.value : '';
        const usadas = Number(avisos.dataset.usadas || 0);
        const plan = Number(avisos.dataset.clasesPlan || 0);
        const recuperos = Number(avisos.dataset.recuperos || 0);
        let texto = '';
        if ((t === 'recurrente' || t === 'temporal') && !plan) {
            texto = 'No tiene un plan vigente. Podés cargarla igual, pero no la cubre ningún plan.';
        } else if ((t === 'recurrente' || t === 'temporal') && usadas >= plan) {
            texto = 'Ya usa las ' + plan + ' clases semanales de su plan. Podés cargarla igual: queda por encima del plan.';
        } else if (t === 'recupero' && !recuperos) {
            texto = 'No tiene ausencias para recuperar. Podés cargarlo igual como recupero (no cuenta en su plan).';
        }
        avisos.hidden = !texto;
        avisos.querySelector('[data-avisos-texto]').textContent = texto;
    }

    // Filtro por sede
    picker.querySelectorAll('[data-sede]').forEach(function (chip) {
        if (chip.tagName !== 'BUTTON') return;
        chip.addEventListener('click', function () {
            const sede = chip.dataset.sede;
            picker.querySelectorAll('button[data-sede]').forEach(function (c) { c.classList.toggle('is-active', c === chip); });
            let visibles = 0;
            picker.querySelectorAll('[data-dia]').forEach(function (dia) {
                let alguna = false;
                dia.querySelectorAll('.rs-op').forEach(function (op) {
                    const ver = !sede || op.dataset.sede === sede || op.querySelector('input').checked;
                    op.hidden = !ver;
                    if (ver) alguna = true;
                });
                dia.hidden = !alguna;
                if (alguna) visibles++;
            });
            picker.querySelector('[data-sin-clases]').hidden = visibles > 0;
        });
    });

    form.addEventListener('change', function (e) {
        if (e.target.name === 'tipo_reserva') { actualizarLibres(); actualizarFechas(); actualizarAvisos(); }
        if (e.target.name === campo) actualizarFechas();
    });
    actualizarLibres();
    actualizarFechas();
    actualizarAvisos();
})();
